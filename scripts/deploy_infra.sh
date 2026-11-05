#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOYMENT_ENVIRONMENT:?Set DEPLOYMENT_ENVIRONMENT to a stable resource environment name}"
: "${AZURE_LOCATION:?Set AZURE_LOCATION to the Azure resource and deployment region}"
: "${AZURE_DEPLOYMENT_PRINCIPAL_ID:?Set AZURE_DEPLOYMENT_PRINCIPAL_ID to the deployer service principal object ID}"

if [[ ! "$AZURE_DEPLOYMENT_PRINCIPAL_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
    echo "AZURE_DEPLOYMENT_PRINCIPAL_ID must be a service principal object ID (UUID)." >&2
    exit 1
fi

bundle=$(cd "${1:?Provide the CI artifact directory}" && pwd)
for file in infra/main.bicep infra/cicd.parameters.json app.zip; do
    if [[ ! -f "$bundle/$file" ]]; then
        echo "Required CI artifact is missing: $bundle/$file" >&2
        exit 1
    fi
done

az deployment sub create \
    --name "foundry-${DEPLOYMENT_ENVIRONMENT}" \
    --location "$AZURE_LOCATION" \
    --template-file "$bundle/infra/main.bicep" \
    --parameters "@$bundle/infra/cicd.parameters.json" \
        environmentName="$DEPLOYMENT_ENVIRONMENT" \
        location="$AZURE_LOCATION" \
        principalId="$AZURE_DEPLOYMENT_PRINCIPAL_ID" \
        principalType=ServicePrincipal \
        templateValidationMode=false \
    --query properties.outputs \
    --output json > "$bundle/deployment-outputs.json"

jq -er '.AZURE_RESOURCE_GROUP.value, .SERVICE_API_NAME.value, .SERVICE_API_URI.value' \
    "$bundle/deployment-outputs.json"
