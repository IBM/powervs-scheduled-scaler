##############################################################################
# Resource Group
##############################################################################

module "resource_group" {
  source  = "terraform-ibm-modules/resource-group/ibm"
  version = "1.3.0"
  # if an existing resource group is not set (null) create a new one using prefix
  resource_group_name          = var.resource_group == null ? "${var.prefix}-resource-group" : null
  existing_resource_group_name = var.resource_group
}

data "ibm_resource_instance" "location" {
  name              = var.workspace_name
  resource_group_id = module.resource_group.resource_group_id
  location          = var.ibmcloud_pvs_datacenter
  service           = "power-iaas"
}

##############################################################################
# PowerVS
##############################################################################

data "ibm_pi_workspace" "pvs_workspace" {
  pi_cloud_instance_id = data.ibm_resource_instance.location.guid
}

data "ibm_pi_instances" "pvs_instances" {
  pi_cloud_instance_id = data.ibm_resource_instance.location.guid
}

locals {
  instances_details_json = jsonencode([
    for inst in data.ibm_pi_instances.pvs_instances.pvm_instances : {
      instance_id   = inst.pvm_instance_id
      instance_name = inst.server_name
      cpu           = inst.processors
      ram           = inst.memory
    }
  ])
  project_name = var.code_engine_project_name == null ? var.prefix : var.code_engine_project_name
}

##############################################################################
# IAM
##############################################################################

resource "ibm_iam_service_id" "sid" {
  name        = "${var.prefix}-sid"
  description = "Do not delete! Used as operator to manage service bindings of Code Engine project '${local.project_name}'"
}

resource "ibm_iam_service_policy" "power_iaas_policy" {
  iam_id      = ibm_iam_service_id.sid.iam_id
  roles       = ["Manager"]
  description = "IAM Service Policy for PowerVS"
  resources {
    service              = "power-iaas"
    resource_instance_id = data.ibm_pi_workspace.pvs_workspace.id
  }

  transaction_id = "terraformServicePolicy"
}

##############################################################################
# Configure registry access for Region
##############################################################################
resource "ibm_iam_service_policy" "container_registry_policy" {
  iam_id      = ibm_iam_service_id.sid.iam_id
  roles       = ["Manager"]
  description = "IAM Service Policy for Container Registry"
  resources {
    service = "container-registry"
    region  = var.ibmcloud_region
  }

  transaction_id = "terraformServicePolicy"
}

resource "ibm_iam_service_policy" "iam_policy" {
  iam_id      = ibm_iam_service_id.sid.iam_id
  roles       = ["Administrator"]
  description = "IAM Service Policy for IAM Identity Service"
  resources {
    service       = "iam-identity"
    resource_type = "serviceid"
    resource      = ibm_iam_service_id.sid.id
  }

  transaction_id = "terraformServicePolicy"
}

resource "ibm_iam_service_policy" "resource_group_policy" {
  iam_id      = ibm_iam_service_id.sid.iam_id
  roles       = ["Viewer"]
  description = "IAM Service Policy for Resource Group"
  resources {
    resource_type = "resource-group"
    resource      = module.resource_group.resource_group_id
  }

  transaction_id = "terraformServicePolicy"
}

resource "ibm_iam_service_policy" "code_engine_policy" {
  iam_id      = ibm_iam_service_id.sid.iam_id
  roles       = ["Writer", "Compute Environment Administrator", "Service Configuration Reader", "Administrator"]
  description = "IAM Service Policy for Code Engine"
  resources {
    service = "codeengine"
  }

  transaction_id = "terraformServicePolicy"
}

resource "ibm_iam_service_api_key" "key" {
  depends_on = [
    ibm_iam_service_policy.code_engine_policy,
    ibm_iam_service_policy.container_registry_policy,
    ibm_iam_service_policy.iam_policy,
    ibm_iam_service_policy.resource_group_policy,
    ibm_iam_service_policy.power_iaas_policy
  ]

  name           = "${var.prefix}-key"
  iam_service_id = ibm_iam_service_id.sid.iam_id
  description    = "API key to establish an integration with container registry location ${var.ibmcloud_region} for Code Engine project ${local.project_name}"
}

# ##############################################################################
# # Code Engine
# ##############################################################################

resource "null_resource" "project_replace" {
  count = var.enable_project_replace ? 1 : 0

  triggers = {
    ibmcloud_api_key = var.ibmcloud_api_key
    region           = var.ibmcloud_region
    resource_group   = module.resource_group.resource_group_id
    project_name     = local.project_name
  }

  provisioner "local-exec" {
    command = "${path.module}/scripts/replace_project.sh"
    environment = {
      IBM_CLOUD_API_KEY = self.triggers.ibmcloud_api_key
      REGION            = self.triggers.region
      RESOURCE_GROUP    = self.triggers.resource_group
      PROJECT           = self.triggers.project_name
    }
  }
}

resource "ibm_code_engine_project" "code_engine_project_instance" {
  name              = local.project_name
  resource_group_id = module.resource_group.resource_group_id

  depends_on = [null_resource.project_replace]
}

resource "ibm_code_engine_secret" "cr_secret" {
  project_id = ibm_code_engine_project.code_engine_project_instance.project_id
  name       = "container-registry-secret-${var.ibmcloud_region}"
  format     = "registry"
  data = {
    password = ibm_iam_service_api_key.key.apikey
    server   = "private.${var.registry_domain_name}"
    username = "iamapikey"
  }
}

resource "ibm_code_engine_secret" "app_secret" {
  project_id = ibm_code_engine_project.code_engine_project_instance.project_id
  name       = "${var.prefix}-secret"
  format     = "generic"
  data       = { "IBM_CLOUD_API_KEY" = ibm_iam_service_api_key.key.apikey }
}

resource "ibm_code_engine_config_map" "app_config_map" {
  project_id = ibm_code_engine_project.code_engine_project_instance.project_id
  name       = "${var.prefix}-config-map"
  data = {
    "CRN"                             = data.ibm_pi_workspace.pvs_workspace.pi_workspace_details[0].crn
    "CODE_ENGINE_PROJECT_NAME"        = local.project_name
    "CODE_ENGINE_RESOURCE_GROUP_NAME" = module.resource_group.resource_group_name
    "CODE_ENGINE_REGION"              = var.ibmcloud_region
    "POWERVS_REGION"                  = var.ibmcloud_region
  }
}

resource "null_resource" "build_function_current_state" {
  provisioner "local-exec" {
    command = "${path.module}/scripts/create_function.sh"
    environment = {
      IBM_CLOUD_API_KEY = self.triggers.ibmcloud_api_key
      REGION            = self.triggers.region
      RESOURCE_GROUP    = self.triggers.resource_group
      PROJECT_ID        = self.triggers.ce_project_id
      FUNCTION_NAME     = self.triggers.function_name
      VISIBILITY        = "public"
      SOURCE_FOLDER     = self.triggers.source_folder
      CONFIG_MAPS       = "${self.triggers.fn_config_map}"
      SECRETS           = self.triggers.fn_secret
      CR_SECRET         = self.triggers.cr_secret
      OUTPUT_FILE       = "${path.module}/${self.triggers.function_name}.json"
    }
  }

  triggers = {
    ibmcloud_api_key = var.ibmcloud_api_key
    region           = var.ibmcloud_region
    resource_group   = module.resource_group.resource_group_id
    ce_project_id    = ibm_code_engine_project.code_engine_project_instance.project_id
    function_name    = "${var.prefix}-current-state-fn"
    source_folder    = "${path.module}/${var.prefix}-current-state-fn"
    fn_config_map    = ibm_code_engine_config_map.app_config_map.name
    fn_secret        = ibm_code_engine_secret.app_secret.name
    cr_secret        = ibm_code_engine_secret.cr_secret.name

    folder_hash = sha256(join("", [for f in fileset("${path.module}/${var.prefix}-current-state-fn", "**") : filemd5("${path.module}/${var.prefix}-current-state-fn/${f}")]))
  }

  provisioner "local-exec" {
    when    = destroy
    command = "${path.module}/scripts/cleanup.sh"
    environment = {
      IBM_CLOUD_API_KEY = self.triggers.ibmcloud_api_key
      REGION            = self.triggers.region
      RESOURCE_GROUP    = self.triggers.resource_group
      FUNCTION_NAME     = self.triggers.function_name
      JSON_FILE         = "${path.module}/${self.triggers.function_name}.json"
    }
  }
}

resource "null_resource" "build_function_scale_down" {
  provisioner "local-exec" {
    command = "${path.module}/scripts/create_function.sh"
    environment = {
      IBM_CLOUD_API_KEY = self.triggers.ibmcloud_api_key
      REGION            = self.triggers.region
      RESOURCE_GROUP    = self.triggers.resource_group
      PROJECT_ID        = self.triggers.ce_project_id
      FUNCTION_NAME     = self.triggers.function_name
      VISIBILITY        = "project"
      SOURCE_FOLDER     = self.triggers.source_folder
      CONFIG_MAPS       = "${self.triggers.fn_config_map},${self.triggers.pvs_config_map}"
      SECRETS           = self.triggers.fn_secret
      CR_SECRET         = self.triggers.cr_secret
      OUTPUT_FILE       = "${path.module}/${self.triggers.function_name}.json"
    }
  }

  triggers = {
    ibmcloud_api_key = var.ibmcloud_api_key
    region           = var.ibmcloud_region
    resource_group   = module.resource_group.resource_group_id
    ce_project_id    = ibm_code_engine_project.code_engine_project_instance.project_id
    function_name    = "${var.prefix}-down-fn"
    source_folder    = "${path.module}/${var.prefix}-fn"
    fn_config_map    = ibm_code_engine_config_map.app_config_map.name
    pvs_config_map   = ibm_code_engine_config_map.ce_scale_down_config_map.name
    fn_secret        = ibm_code_engine_secret.app_secret.name
    cr_secret        = ibm_code_engine_secret.cr_secret.name

    folder_hash = sha256(join("", [for f in fileset("${path.module}/${var.prefix}-fn", "**") : filemd5("${path.module}/${var.prefix}-fn/${f}")]))
  }

  provisioner "local-exec" {
    when    = destroy
    command = "${path.module}/scripts/cleanup.sh"
    environment = {
      IBM_CLOUD_API_KEY = self.triggers.ibmcloud_api_key
      REGION            = self.triggers.region
      RESOURCE_GROUP    = self.triggers.resource_group
      FUNCTION_NAME     = self.triggers.function_name
      JSON_FILE         = "${path.module}/${self.triggers.function_name}.json"
    }
  }
}

data "ibm_code_engine_function" "scale_down_function" {
  depends_on = [null_resource.build_function_scale_down]
  name       = "${var.prefix}-down-fn"
  project_id = ibm_code_engine_project.code_engine_project_instance.project_id
}

resource "ibm_code_engine_function" "scale_up_function" {
  depends_on = [null_resource.build_function_scale_down]

  project_id         = ibm_code_engine_project.code_engine_project_instance.project_id
  name               = "${var.prefix}-up-fn"
  runtime            = "python-3.13"
  code_reference     = replace(data.ibm_code_engine_function.scale_down_function.code_reference, "cr://", "")
  code_binary        = true
  code_secret        = data.ibm_code_engine_function.scale_down_function.code_secret
  scale_cpu_limit    = "0.25"
  scale_memory_limit = "1G"

  run_env_variables {
    reference = ibm_code_engine_config_map.app_config_map.name
    type      = "config_map_full_reference"
  }
  run_env_variables {
    reference = ibm_code_engine_config_map.ce_scale_up_config_map.name
    type      = "config_map_full_reference"
  }
  run_env_variables {
    reference = ibm_code_engine_secret.app_secret.name
    type      = "secret_full_reference"
  }
}

resource "ibm_code_engine_config_map" "ce_scale_up_config_map" {
  project_id = ibm_code_engine_project.code_engine_project_instance.project_id
  name       = "pvs-scale-up-config"
  data = {
    "pvs_scale_config" = local.instances_details_json
  }
}
resource "ibm_code_engine_config_map" "ce_scale_down_config_map" {
  project_id = ibm_code_engine_project.code_engine_project_instance.project_id
  name       = "pvs-scale-down-config"
  data = {
    "pvs_scale_config" = local.instances_details_json
  }
}

resource "null_resource" "post_configuration" {
  depends_on = [
    null_resource.build_function_scale_down,
    ibm_code_engine_function.scale_up_function
  ]
  provisioner "local-exec" {
    command = <<COMMAND
       ibmcloud login --apikey "${self.triggers.ibmcloud_api_key}" -r "${self.triggers.region}" -g "${self.triggers.resource_group}" --quiet
       ibmcloud code-engine project select --id "${self.triggers.ce_project_id}" --quiet
       ibmcloud code-engine subscription cron create \
        --name "scale-down-cron-job" \
        --destination-type function \
        --destination "${self.triggers.scale_down_fn}" \
        --schedule "${self.triggers.cron_down}" \
        --wait --wait-timeout 300 --quiet && \
       ibmcloud code-engine subscription cron create \
        --name "scale-up-cron-job" \
        --destination-type function \
        --destination "${self.triggers.scale_up_fn}" \
        --schedule "${self.triggers.cron_up}" \
        --wait --wait-timeout 300 --quiet || exit 1
    COMMAND
  }

  triggers = {
    ibmcloud_api_key = var.ibmcloud_api_key
    region           = var.ibmcloud_region
    resource_group   = module.resource_group.resource_group_id
    ce_project_id    = ibm_code_engine_project.code_engine_project_instance.project_id
    scale_down_fn    = "${var.prefix}-down-fn"
    scale_up_fn      = "${var.prefix}-up-fn"
    cron_down        = var.cron_expression_scale_down
    cron_up          = var.cron_expression_scale_up
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<COMMAND
       ibmcloud login --apikey "${self.triggers.ibmcloud_api_key}" -r "${self.triggers.region}" -g "${self.triggers.resource_group}" --quiet
       ibmcloud code-engine project select --id "${self.triggers.ce_project_id}" --quiet && \
       ibmcloud code-engine subscription cron delete --name "scale-down-cron-job" --ignore-not-found --force --quiet && \
       ibmcloud code-engine subscription cron delete --name "scale-up-cron-job" --ignore-not-found --force --quiet
     COMMAND
  }
}
