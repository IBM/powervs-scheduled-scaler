#!/bin/bash

set -e

# Validate input
if [[ -z "$IBM_CLOUD_API_KEY" || -z "$REGION" || -z "$RESOURCE_GROUP" || -z "$PROJECT_ID" || -z "$FUNCTION_NAME" || -z "$VISIBILITY" || -z "$SOURCE_FOLDER" || -z "$CR_SECRET" || -z "$OUTPUT_FILE" ]]; then
    echo "IBM_CLOUD_API_KEY, REGION, REGION, RESOURCE_GROUP, PROJECT_ID, FUNCTION_NAME, VISIBILITY, SOURCE_FOLDER, CR_SECRET and OUTPUT_FILE variable are required"
    exit 1
fi

# Login to IBM Cloud
ibmcloud login --apikey "$IBM_CLOUD_API_KEY" -r "$REGION" -g "$RESOURCE_GROUP" --quiet

# Select code engine project
ibmcloud code-engine project select --id "$PROJECT_ID" --quiet

# Build the --env-from-configmap arguments dynamically
CONFIGMAP_ARGS=""
IFS=',' read -ra CONFIGMAPS <<<"$CONFIG_MAPS"
for cm in "${CONFIGMAPS[@]}"; do
    CONFIGMAP_ARGS+=" --env-from-configmap \"$cm\""
done

# Build --env-from-secret arguments dynamically
SECRET_ARGS=""
IFS=',' read -ra SECRETS <<<"$SECRETS"
for secret in "${SECRETS[@]}"; do
    SECRET_ARGS+=" --env-from-secret \"$secret\""
done

OUTPUT=$(eval ibmcloud code-engine fn create \
    --name "$FUNCTION_NAME" \
    -v "$VISIBILITY" --wait --wait-timeout 300 --quiet \
    --runtime python-3.13 \
    --build-source "$SOURCE_FOLDER" \
    --cpu 0.25 \
    --memory 1G \
    $CONFIGMAP_ARGS \
    $SECRET_ARGS \
    --code-bundle-secret "$CR_SECRET" \
    --output json) || exit 1

# Save output to JSON file
echo "$OUTPUT" >"$OUTPUT_FILE"
