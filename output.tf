output "pvs_current_state_fn_url" {
  description = "Endpoint for current state function"
  value = data.ibm_code_engine_function.current_state_function.endpoint
}

output "pvs_scale_down_fn_url" {
  description = "Endpoint for scale down function"
  value = data.ibm_code_engine_function.scale_down_function.endpoint_internal
}

output "pvs_scale_up_fn_url" {
  description = "Endpoint for scale up function"
  value = ibm_code_engine_function.scale_up_function.endpoint_internal
}
