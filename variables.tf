variable "ibmcloud_api_key" {
  description = "IBM Cloud API key"
  type        = string
  sensitive   = true
}

variable "ibmcloud_region" {
  description = "IBM Cloud Region"
  type        = string
  default     = "eu-de"
}

variable "ibmcloud_pvs_datacenter" {
  description = "IBM Cloud Zone for PowerVS workspace"
  type        = string
  default     = "eu-de-1"
}

variable "prefix" {
  description = "A unique identifier for resources. Must begin with a lowercase letter and end with a lowerccase letter or number. This prefix will be prepended to any resources provisioned by this template. Prefixes must be 16 or fewer characters."
  type        = string
  default     = "pvs-scale"

  validation {
    error_message = "Prefix must begin with a lowercase letter and contain only lowercase letters, numbers, and - characters. Prefixes must end with a lowercase letter or number and be 16 or fewer characters."
    condition     = can(regex("^([a-z]|[a-z][-a-z0-9]*[a-z0-9])$", var.prefix))
  }
}

variable "resource_group" {
  type = string
}

// Resource arguments for code_engine_project
variable "code_engine_project_name" {
  description = "The name of the project."
  type        = string
  default     = null
}

variable "workspace_name" {
  description = "Workspace Name"
  type        = string
}

variable "registry_domain_name" {
  description = "Container registry domain name"
  type = string
  default = "de.icr.io"
  validation {
    condition     = can(regex("^(icr.io|de.icr.io|us.icr.io|es.icr.io|uk.icr.io|jp.icr.io|jp2.icr.io|br.icr.io|au.icr.io|ca.icr.io)$", var.registry_domain_name))
    error_message = "Value must be one of: icr.io, de.icr.io, us.icr.io, es.icr.io, uk.icr.io, jp.icr.io, jp2.icr.io, br.icr.io, au.icr.io, ca.icr.io"
  }
}

variable "image_tag" {
  description = "Tag of the image in container registry"
  type = string
  default = "latest"
}

variable "cron_expression_scale_down" {
  description = "Define the recurring timing of the events generated for scale down subscription in UTC."
  type = string
  default = "0 15 * * 1-5"
}

variable "cron_expression_scale_up" {
  description = "Define the recurring timing of the events generated for scale up subscription in UTC."
  type = string
  default = "0 6 * * 1-5"
}
