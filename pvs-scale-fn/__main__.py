import json
import os
import re

import requests
from ibm_cloud_sdk_core import BaseService, ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core.utils import strip_extra_slashes
from requests import JSONDecodeError

def get_service_url_for_region(region: str) -> str:
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

def get_service_instance_from_crn(crn: str) -> str | None:
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
        raise ValueError('The crn is required')
    pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    match = re.search(pattern, crn, re.IGNORECASE)
    return match.group(0) if match else None

def get_json_error(status: int, title: str, message: str):
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

def return_json_body(body: dict, code: int):
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

def main(params):
    config = json.loads(os.getenv("pvs_scale_config"))
    authenticator = IAMAuthenticator(os.getenv("IBM_CLOUD_API_KEY"))
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {authenticator.token_manager.get_token()}",
        "CRN": os.getenv("CRN")
    }
    path_param_keys = ['cloud_instance_id', 'pvm_instance_id']
    cloud_instance_id = get_service_instance_from_crn(os.getenv("CRN"))
    output = []
    for instance in config:
        pvm_instance_id = instance["instance_id"]
        path_param_values = BaseService.encode_path_vars(cloud_instance_id, pvm_instance_id)
        path_param_dict = dict(zip(path_param_keys, path_param_values))
        url = '/cloud-instances/{cloud_instance_id}/pvm-instances/{pvm_instance_id}'.format(**path_param_dict)
        url = strip_extra_slashes(get_service_url_for_region(os.getenv("POWERVS_REGION")) + url)
        body = {
            "processors": instance["cpu"],
            "memory": instance["ram"]
        }
        response = requests.put(url=url, data=json.dumps(body), headers=headers)
        if 200 <= response.status_code <= 204:
            try:
                result = response.json(strict=False)
                output.append({pvm_instance_id: {"message": "Scaled completed successfully", "code": response.status_code}})
            except JSONDecodeError as e:
                return get_json_error(e.status_code, "error", e.message)
        else:
            output.append({pvm_instance_id: {"message": response.content, "code": response.status_code}})

    return return_json_body(output, 200)
