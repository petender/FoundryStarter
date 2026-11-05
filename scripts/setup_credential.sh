#!/usr/bin/env bash
set -euo pipefail

if ! az account show --output none 2>/dev/null; then
    tenantId=$(azd env get-value AZURE_TENANT_ID)
    az login --tenant "$tenantId" --output none
fi

while true; do
    read -rp "Create a username (no spaces): " username
    if [[ -n "$username" && ! "$username" =~ [[:space:]] ]]; then break; fi
    echo "Username cannot be empty or contain spaces." >&2
done

while true; do
    read -rsp "Create a password (no spaces): " password
    echo
    read -rsp "Confirm password: " confirmation
    echo
    if [[ -n "$password" && ! "$password" =~ [[:space:]] && "$password" == "$confirmation" ]]; then break; fi
    echo "Passwords must match, be nonempty, and contain no spaces." >&2
done

resourceGroup=$(azd env get-value AZURE_RESOURCE_GROUP)
appName=$(azd env get-value SERVICE_API_NAME)
subscription=$(azd env get-value AZURE_SUBSCRIPTION_ID)
settingsFile=$(mktemp)
chmod 600 "$settingsFile"
trap 'rm -f "$settingsFile"; unset password confirmation' EXIT

WEB_APP_USERNAME="$username" WEB_APP_PASSWORD="$password" python3 -c \
    'import json, os, sys; json.dump({k: os.environ[k] for k in ("WEB_APP_USERNAME", "WEB_APP_PASSWORD")}, sys.stdout)' \
    > "$settingsFile"

az webapp config appsettings set --subscription "$subscription" --resource-group "$resourceGroup" \
    --name "$appName" --settings "@$settingsFile" --output none
az webapp restart --subscription "$subscription" --resource-group "$resourceGroup" --name "$appName" --output none
echo "Basic authentication configured for $appName."
