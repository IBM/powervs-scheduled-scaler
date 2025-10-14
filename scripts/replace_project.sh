#!/bin/bash

set -e

# Validate input
if [[ -z "$PROJECT" || -z "$REGION" || -z "$RESOURCE_GROUP" || -z "$IBM_CLOUD_API_KEY" ]]; then
    echo "IBM_CLOUD_API_KEY, RESOURCE_GROUP, REGION and PROJECT variable are required"
    exit 1
fi

# Login to IBM Cloud
ibmcloud login --apikey "$IBM_CLOUD_API_KEY" -r "$REGION" -g "$RESOURCE_GROUP" --quiet

# Check if the project exists
if ibmcloud ce proj get --name $PROJECT --output json &>/dev/null; then
    echo "Project $PROJECT_NAME found. Proceeding with hard delete..."
    ibmcloud ce project delete --name "$PROJECT" --hard --force --wait --wait-timeout 300
else
    echo "Project $PROJECT_NAME does not exist. No action needed."
fi
