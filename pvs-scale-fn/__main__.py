import json
import os
import re
import logging
from typing import Optional, Any

import requests
from ibm_cloud_sdk_core import BaseService, ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core.utils import strip_extra_slashes
from requests import JSONDecodeError, RequestException

# --- Setup logging -------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# --- Utility functions ---------------------------------------------------------

def get_service_url_for_region(region: str) -> Optional[str]:
    """
    Returns the service URL associated with the specified region.
    :param str region: a string representing the region
    :return: The service URL associated with the specified region or None
              if no mapping for the region exists
    :rtype: str
    """
    REGIONAL_ENDPOINTS = {
        'au-syd': 'https://syd.power-iaas.cloud.ibm.com/pcloud/v1',  # Australia (Sydney)
        'br-sao': 'https://sao.power-iaas.cloud.ibm.com/pcloud/v1',  # Brazil (Sao Paulo)
        'ca-mon': 'https://mon.power-iaas.cloud.ibm.com/pcloud/v1',  # Canada (Montreal)
        'ca-tor': 'https://tor.power-iaas.cloud.ibm.com/pcloud/v1',  # Canada (Toronto)
        'eu-de': 'https://eu-de.power-iaas.cloud.ibm.com/pcloud/v1',  # Germany (Frankfurt)
        'eu-es': 'https://mad.power-iaas.cloud.ibm.com/pcloud/v1',  # Spain (Madrid)
        'eu-gb': 'https://lon.power-iaas.cloud.ibm.com/pcloud/v1',  # United Kingdom (London)
        'jp-osa': 'https://osa.power-iaas.cloud.ibm.com/pcloud/v1',  # Japan (Osaka)
        'jp-tok': 'https://tok.power-iaas.cloud.ibm.com/pcloud/v1',  # Japan (Tokyo)
        'us-east': 'https://us-east.power-iaas.cloud.ibm.com/pcloud/v1',  # US East (Washington DC)ß
        'us-south': 'https://us-south.power-iaas.cloud.ibm.com/pcloud/v1',  # US South (Dallas)
        'in-che': 'https://che.power-iaas.cloud.ibm.com/pcloud/v1',  # India (Chennai)
    }
    return REGIONAL_ENDPOINTS.get(region, None)

def get_service_instance_from_crn(crn: str) -> Optional[str]:
    """
    Extracts the UUID (service_instance) from an IBM Cloud CRN.

    This function takes a CRN (Cloud Resource Name) as input and returns the service instance UUID if found.
    The CRN format is expected to be 'provider-type-name-region-identifier'. The identifier part is assumed to contain
    the UUID in a specific format: '8-4-4-4-12 hexadecimal characters'.

    Args:
        crn (str): The CRN from which to extract the service instance UUID.

    Returns:
        str: The extracted UUID if found, otherwise None.
    """
    if not crn:
        raise ValueError('The CRN is required')
    pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    match = re.search(pattern, crn, re.IGNORECASE)
    return match.group(0) if match else None

def get_json_error(status: int, title: str, message: str) -> dict[str, Any]:
    """
    Create a JSON error response.

    This function constructs a dictionary representing an HTTP response with JSON body,
    suitable for error handling in web applications.

    Args:
        status (int): The HTTP status code indicating the type of error.
        title (str): A short, human-readable error title.
        message (str): A detailed description of the error.

    Returns:
        dict: A dictionary containing the HTTP response details including headers, status code, and error body.
    """
    logger.error(f"{title}: {message}")
    return {
        "headers": {
            "Content-Type": "application/json",
        },
        "statusCode": status,
        "body": {
            "error": title,
            "message": message,
        },
    }

def return_json_body(body: dict, code: int) -> dict[str, Any]:
    """
    Constructs a dictionary representing a JSON response.

    This function creates a dictionary that mimics the structure of a JSON response.
    It includes headers, status code, and the body of the response.

    Args:
        body (str): The body content of the response.

    Returns:
        dict: A dictionary representing the JSON response.
    """
    return {
        "headers": {
            "Content-Type": "application/json",
        },
        "statusCode": code,
        "body": {
            "return": body
        }
    }

# -------------------------------------------
# Main entry point
# -------------------------------------------

def main(params) -> dict[str, Any]:
    """Entrypoint for IBM Cloud Function or local execution."""
    try:
        api_key = os.getenv("IBM_CLOUD_API_KEY")
        crn = os.getenv("CRN")
        region = os.getenv("POWERVS_REGION")
        config_env = os.getenv("pvs_scale_config")

        if not all([api_key, crn, region, config_env]):
            missing = [k for k, v in {
                "IBM_CLOUD_API_KEY": api_key,
                "CRN": crn,
                "POWERVS_REGION": region,
                "pvs_scale_config": config_env,
            }.items() if not v]
            return get_json_error(400, "MissingConfiguration", f"Missing env vars: {', '.join(missing)}")

        try:
            config = json.loads(config_env)
            if not isinstance(config, list):
                raise ValueError("Configuration must be a list of instances.")
        except (ValueError, json.JSONDecodeError) as e:
            return get_json_error(400, "InvalidConfiguration", str(e))

        authenticator = IAMAuthenticator(api_key)
        token = authenticator.token_manager.get_token()
        if not token:
            return get_json_error(401, "AuthenticationError", "Failed to obtain IAM token")

        service_url = get_service_url_for_region(region)
        if not service_url:
            return get_json_error(400, "InvalidRegion", f"Unknown region: {region}")

        cloud_instance_id = get_service_instance_from_crn(crn)
        if not cloud_instance_id:
            return get_json_error(400, "InvalidCRN", f"Cannot extract instance ID from CRN: {crn}")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "CRN": crn
        }

        path_param_keys = ['cloud_instance_id', 'pvm_instance_id']
        output = []
        for instance in config:
            pvm_instance_id = instance.get("instance_id")
            cpu = instance.get("cpu")
            ram = instance.get("ram")

            if not all([pvm_instance_id, cpu, ram]):
                output.append({
                    "instance_id": pvm_instance_id or "unknown",
                    "message": "Missing instance_id, cpu, or ram",
                    "code": 400,
                })
                continue

            path_param_values = BaseService.encode_path_vars(cloud_instance_id, pvm_instance_id)
            path_param_dict = dict(zip(path_param_keys, path_param_values))
            url = '/cloud-instances/{cloud_instance_id}/pvm-instances/{pvm_instance_id}'.format(**path_param_dict)
            url = strip_extra_slashes(get_service_url_for_region(os.getenv("POWERVS_REGION")) + url)

            body = {"processors": cpu, "memory": ram}
            try:
                response = requests.put(url=url, json=json.dumps(body), headers=headers, timeout=15)
                if 200 <= response.status_code <= 204:
                    try:
                        result = response.json(strict=False)
                        message = result.get("message", "Scaled successfully")
                        output.append({pvm_instance_id: {"message": message, "code": response.status_code}})
                    except JSONDecodeError as e:
                        return get_json_error(e.status_code, "error", "no JSON in response")
                else:
                    logger.warning(f"Scaling failed for {pvm_instance_id}: {response.text}")
                    output.append({pvm_instance_id: {"message": response.text, "code": response.status_code}})
            except RequestException as e:
                logger.exception(f"Request error for {pvm_instance_id}")
                output.append({
                    pvm_instance_id: {"message": str(e), "code": 500}
                })

        return return_json_body(output, 200)

    except Exception as e:
        logger.exception("Unexpected error in main")
        return get_json_error(500, "InternalError", str(e))
