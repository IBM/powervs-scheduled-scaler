import json
import os
import re
import logging
from typing import Optional, Dict, List, Any

import requests
from ibm_cloud_sdk_core import ApiException, BaseService, DetailedResponse
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core.utils import strip_extra_slashes
from ibm_code_engine_sdk.code_engine_v2 import CodeEngineV2, ProjectsPager, ConfigMapsPager
from requests import JSONDecodeError

# -------------------------------------------
# Logging setup
# -------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# -------------------------------------------
# Utility functions
# -------------------------------------------

def get_service_url_for_region(region: str, service: str) -> Optional[str]:
    """
    Returns the service URL associated with the specified region.
    :param str region: a string representing the region
    :param str service: code_engine or power_iaas
    :return: The service URL associated with the specified region or None
              if no mapping for the region exists
    :rtype: str
    """
    if not region or not service:
        logger.error("Missing required parameters: region or service")
        return None

    POWER_CLOUD_REGIONAL_ENDPOINTS = {
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

    CODE_ENGINE_REGIONAL_ENDPOINTS = {
        'au-syd': 'https://api.us-south.codeengine.cloud.ibm.com/v2',  # Australia (Sydney)
        'br-sao': 'https://api.br-sao.codeengine.cloud.ibm.com/v2',  # Brazil (Sao Paulo)
        'ca-tor': 'https://api.ca-tor.codeengine.cloud.ibm.com/v2',  # Canada (Toronto)
        'eu-de': 'https://api.eu-de.codeengine.cloud.ibm.com/v2',  # Germany (Frankfurt)
        'eu-es': 'https://api.eu-es.codeengine.cloud.ibm.com/v2',  # Spain (Madrid)
        'eu-gb': 'https://api.eu-gb.codeengine.cloud.ibm.com/v2',  # United Kingdom (London)
        'jp-osa': 'https://api.jp-osa.codeengine.cloud.ibm.com/v2',  # Japan (Osaka)
        'jp-tok': 'https://api.jp-tok.codeengine.cloud.ibm.com/v2',  # Japan (Tokyo)
        'us-east': 'https://api.us-east.codeengine.cloud.ibm.com/v2',  # US East (Washington DC)
        'us-south': 'https://api.us-south.codeengine.cloud.ibm.com/v2',  # US South (Dallas)
    }
    if service == "code_engine":
        return CODE_ENGINE_REGIONAL_ENDPOINTS.get(region, None)
    elif service == "power_iaas":
        return POWER_CLOUD_REGIONAL_ENDPOINTS.get(region, None)
    else:
        raise ValueError(f"Unknown service type: {service}")


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
        raise ValueError('CRN is required')

    pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    match = re.search(pattern, crn, re.IGNORECASE)
    return match.group(0) if match else None


def get_json_error(status: int, title: str, message: str)-> Dict[str, Any]:
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
    logger.error(f"[{status}] {title}: {message}")
    return {
        "headers": { "Content-Type": "application/json"},
        "statusCode": status,
        "body": { "error": title, "message": message}
    }


def return_json_body(body: str) -> Dict[str, Any]:
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
        "headers": { "Content-Type": "application/json"},
        "statusCode": 200,
        "body": {"return": body}
    }


def get_paged_results(pager) -> List[Any]:
    """
    Retrieves all results from a paginated data source.

    This function iterates through all pages of data provided by the 'pager' object,
    appending each page's results to a list. It continues this process until the
    'pager' object indicates no more pages are available.

    Args:
        pager (Pager): An object that provides access to paginated data.
            It must have a 'has_next' method to check for more pages and a
            'get_next' method to retrieve the next page's results.

    Returns:
        list: A list containing all results from all pages.

    Raises:
        AssertionError: If 'get_next' returns None, indicating an unexpected state
            in the 'pager' object.
    """
    results = []
    try:
        while pager.has_next():
            next_page = pager.get_next()
            if not next_page:
                logger.warning("Received empty page from pager")
                break
            results.extend(next_page)
    except Exception as e:
        logger.exception("Error while paginating results: %s", e)
    return results



def get_instances_details(crn: str = None, authenticator: IAMAuthenticator = None) -> DetailedResponse:
    """
    Fetches details of PVM instances for a given cloud instance identified by CRN.

    Args:
    crn (str, optional): The Cloud Resource Name (CRN) of the cloud instance. Defaults to None.
    authenticator (IAMAuthenticator, optional): An authenticator instance for IBM Cloud services. Defaults to None.

    Returns:
    DetailedResponse: An object containing the response details, including the response, headers, and status code.

    Raises:
    ApiException: If there is an error processing the HTTP response.
    """
    if not crn:
        raise ValueError("CRN must be provided")
    if not authenticator:
        raise ValueError("Authenticator must be provided")

    region = os.getenv("CODE_ENGINE_REGION")
    if not region:
        raise EnvironmentError("Missing environment variable CODE_ENGINE_REGION")


    base_url = get_service_url_for_region(region, "power_iaas")
    if not base_url:
        raise ValueError(f"No Power IaaS endpoint found for region '{region}'")

    cloud_instance_id = get_service_instance_from_crn(crn)
    if not cloud_instance_id:
        raise ValueError("Unable to extract cloud_instance_id from CRN")

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {authenticator.token_manager.get_token()}",
        "CRN": crn,
    }
    path_param_keys = ['cloud_instance_id']
    cloud_instance_id = get_service_instance_from_crn(crn)
    path_param_values = BaseService.encode_path_vars(cloud_instance_id)
    path_param_dict = dict(zip(path_param_keys, path_param_values))

    url = '/cloud-instances/{cloud_instance_id}/pvm-instances'.format(**path_param_dict)
    url = strip_extra_slashes(base_url + url)
    logger.debug(f"Requesting instances from URL: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
    except JSONDecodeError as e:
        raise ApiException(
            code=response.status_code,
            http_response=response,
            message=f"Invalid JSON in response: {e}"
        ) from e
    except requests.RequestException as e:
        raise ApiException(
            code=getattr(e.response, "status_code", 500),
            message=f"HTTP error: {e}"
        ) from e

    return DetailedResponse(response=result, headers=response.headers, status_code=response.status_code)

def get_current_status(authenticator: IAMAuthenticator) -> list[dict]:
    """
    Retrieves the current status of PVS resources and store in a Code Engine config-map.

    Args:
        authenticator (IAMAuthenticator, optional): An optional IBM Cloud authenticator. Defaults to None.

    Returns:
        List[Dict]: A list containing instance details.
    """
    if not authenticator:
        raise ValueError("Authenticator is required")

    project_name = os.getenv("CODE_ENGINE_PROJECT_NAME")
    crn = os.getenv("CRN")
    if not project_name or not crn:
        raise EnvironmentError("Environment variables CODE_ENGINE_PROJECT_NAME and CRN must be set")

    code_engine_service = CodeEngineV2.new_instance()
    all_projects = get_paged_results(ProjectsPager(client=code_engine_service, limit=100))

    project_id = next((p["id"] for p in all_projects if p.get("name") == project_name), None)
    if not project_id:
        raise ValueError(f"Project '{project_name}' not found in Code Engine")

    instances_details = get_instances_details(crn, authenticator)
    result_data = instances_details.get_result()

    if "pvmInstances" not in result_data:
        raise KeyError("Response missing 'pvmInstances' field")

    data = [
        {
            "instance_id": inst.get("pvmInstanceID"),
            "instance_name": inst.get("serverName"),
            "cpu": inst.get("processors"),
            "ram": inst.get("memory"),
        }
        for inst in result_data["pvmInstances"]
        if inst.get("pvmInstanceID")
    ]

    pvs_scale_up_config_str = json.dumps(data, ensure_ascii=False)
    all_config_maps = get_paged_results(ConfigMapsPager(client=code_engine_service, project_id=project_id, limit=100))
    existing = next((m for m in all_config_maps if m.get("name") == "pvs-scale-up-config"), None)
    if existing:
        logger.info("Updating existing ConfigMap 'pvs-scale-up-config'")
        config_map = code_engine_service.get_config_map(project_id=project_id, name="pvs-scale-up-config")
        etag = config_map.get_result().get("entity_tag")
        code_engine_service.replace_config_map(
            project_id=project_id,
            name="pvs-scale-up-config",
            if_match=etag,
            data={"pvs_scale_config" : pvs_scale_up_config_str}
        )
    else:
        logger.info("Creating new ConfigMap 'pvs-scale-up-config'")
        resp = code_engine_service.create_config_map(
            project_id=project_id,
            name="pvs-scale-up-config",
            data={"pvs_scale_config": pvs_scale_up_config_str}
        )

    return data

# -------------------------------------------
# Main entry point
# -------------------------------------------

def main(params):
    """Entrypoint for IBM Cloud Function or local execution."""
    try:
        api_key = os.getenv("IBM_CLOUD_API_KEY")
        if not api_key:
            raise EnvironmentError("Missing IBM_CLOUD_API_KEY environment variable")

        region = os.getenv("CODE_ENGINE_REGION")
        if not region:
            raise EnvironmentError("Missing CODE_ENGINE_REGION environment variable")

        os.environ["CODE_ENGINE_APIKEY"] = os.getenv("IBM_CLOUD_API_KEY")
        os.environ["CODE_ENGINE_AUTH_TYPE"] = "iam"
        os.environ["CODE_ENGINE_URL"] = get_service_url_for_region(os.getenv("CODE_ENGINE_REGION"), "code_engine")

        authenticator = IAMAuthenticator(api_key)
        current_status = get_current_status(authenticator)
        return return_json_body(current_status)

    except ApiException as e:
        logger.exception("API exception occurred")
        return get_json_error(e.code or 500, "ApiException", e.message)
    except Exception as e:
        logger.exception("Unhandled exception")
        return get_json_error(500, "InternalError", str(e))

