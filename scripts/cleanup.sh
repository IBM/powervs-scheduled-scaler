#!/bin/bash

set -e

# Validate input
if [[ -z "$IBM_CLOUD_API_KEY" || -z "$REGION" || -z "$RESOURCE_GROUP" || -z "$FUNCTION_NAME" || -z "$JSON_FILE" ]]; then
    echo "IBM_CLOUD_API_KEY, REGION, RESOURCE_GROUP, FUNCTION_NAME and JSON_FILE variable are required"
    exit 1
fi

ibmcloud login --apikey "$IBM_CLOUD_API_KEY" -r "$REGION" -g "$RESOURCE_GROUP" --quiet
ibmcloud ce fn delete --name "$FUNCTION_NAME" --quiet --force --ignore-not-found

if [ ! -f "$JSON_FILE" ]; then
  echo "File $JSON_FILE not found"
  exit 0
fi

# Set container registry region
ibmcloud cr region-set "$REGION"


# Extract domain, namespace, and image from code_reference, removing "private." if present
read -r domain namespace image tag <<< "$(jq -r '
  .code_reference
  | capture("cr://(?<full_domain>[^/]+)/(?<namespace>[^/]+)/(?<image>[^:@]+):(?<tag>[^@]+)")
  | {
      domain: (.full_domain | sub("^private\\."; "")),
      namespace,
      image,
      tag
    }
  | "\(.domain) \(.namespace) \(.image) \(.tag)"
' "$JSON_FILE")"

# Delete the image
if ! ibmcloud cr image-rm "$domain/$namespace/$image:$tag" --force 2>/dev/null;
then
  echo "Image $domain/$namespace/$image:$tag not found or already deleted. Continuing..."
fi

image_count=$(ibmcloud cr images --restrict "$namespace" --output json | jq length)

if [ "$image_count" -eq 0 ]; then
  echo "Namespace $namespace is empty. Deleting..."
  ibmcloud cr namespace-rm "$namespace" --force
else
  echo "Namespace $namespace still contains images. Skipping deletion."
fi

# Clean up JSON file
rm -f "$JSON_FILE"
