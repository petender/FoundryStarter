$ErrorActionPreference = "Stop"

function Get-AzdValue([string]$Name) {
    $value = azd env get-value $Name
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) {
        throw "Could not read $Name. Run azd up first."
    }
    return $value
}

$tenantId = Get-AzdValue "AZURE_TENANT_ID"
az account show --output none 2>$null
if ($LASTEXITCODE -ne 0) {
    az login --tenant $tenantId --output none
    if ($LASTEXITCODE -ne 0) { throw "Azure login failed." }
}

do {
    $username = Read-Host "Create a username (no spaces)"
} while ([string]::IsNullOrWhiteSpace($username) -or $username -match '\s')

$plainPassword = $null
do {
    $password = Read-Host "Create a password (no spaces)" -AsSecureString
    $confirmation = Read-Host "Confirm password" -AsSecureString
    $plainPassword = [System.Net.NetworkCredential]::new("", $password).Password
    $plainConfirmation = [System.Net.NetworkCredential]::new("", $confirmation).Password
    $valid = $plainPassword -and $plainPassword -notmatch '\s' -and $plainPassword -ceq $plainConfirmation
    if (-not $valid) { Write-Warning "Passwords must match, be nonempty, and contain no spaces." }
} while (-not $valid)

$settingsFile = [System.IO.Path]::GetTempFileName()
try {
    $resourceGroup = Get-AzdValue "AZURE_RESOURCE_GROUP"
    $appName = Get-AzdValue "SERVICE_API_NAME"
    $subscription = Get-AzdValue "AZURE_SUBSCRIPTION_ID"
    @{
        WEB_APP_USERNAME = $username
        WEB_APP_PASSWORD = $plainPassword
    } | ConvertTo-Json | Set-Content -LiteralPath $settingsFile -Encoding utf8

    az webapp config appsettings set --subscription $subscription --resource-group $resourceGroup `
        --name $appName --settings "@$settingsFile" --output none
    if ($LASTEXITCODE -ne 0) { throw "Failed to update App Service authentication settings." }

    az webapp restart --subscription $subscription --resource-group $resourceGroup --name $appName --output none
    if ($LASTEXITCODE -ne 0) { throw "Settings updated, but App Service restart failed." }

    Write-Host "Basic authentication configured for $appName."
} finally {
    Remove-Item -LiteralPath $settingsFile -Force
    $plainPassword = $null
    $plainConfirmation = $null
    $password.Dispose()
    $confirmation.Dispose()
}
