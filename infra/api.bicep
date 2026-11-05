param name string
param location string = resourceGroup().location
param tags object = {}

param appServicePlanName string
param appServiceSku string = 'B1'
param identityName string
param azureExistingAIProjectResourceId string
param chatDeploymentName string
param embeddingDeploymentName string
param aiSearchIndexName string
param embeddingDeploymentDimensions string
param searchServiceEndpoint string
param enableAzureMonitorTracing bool
param azureTracingGenAIContentRecordingEnabled bool
param projectEndpoint string

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: tags
}

var env = [
  {
    name: 'AZURE_CLIENT_ID'
    value: apiIdentity.properties.clientId
  }
  {
    name: 'AZURE_EXISTING_AIPROJECT_RESOURCE_ID'
    value: azureExistingAIProjectResourceId
  }
  {
    name: 'AZURE_AI_CHAT_DEPLOYMENT_NAME'
    value: chatDeploymentName
  }
  {
    name: 'AZURE_AI_EMBED_DEPLOYMENT_NAME'
    value: embeddingDeploymentName
  }
  {
    name: 'AZURE_AI_SEARCH_INDEX_NAME'
    value: aiSearchIndexName
  }
  {
    name: 'AZURE_AI_EMBED_DIMENSIONS'
    value: embeddingDeploymentDimensions
  }
  {
    name: 'RUNNING_IN_PRODUCTION'
    value: 'true'
  }
  {
    name: 'AZURE_AI_SEARCH_ENDPOINT'
    value: searchServiceEndpoint
  }
  {
    name: 'ENABLE_AZURE_MONITOR_TRACING'
    value: string(enableAzureMonitorTracing)
  }
  {
    name: 'AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED'
    value: string(azureTracingGenAIContentRecordingEnabled)
  }
  {
    name: 'AZURE_EXISTING_AIPROJECT_ENDPOINT'
    value: projectEndpoint
  }
]


resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: appServicePlanName
  location: location
  tags: tags
  kind: 'linux'
  sku: {
    name: appServiceSku
    capacity: 1
  }
  properties: {
    reserved: true
  }
}

resource app 'Microsoft.Web/sites@2023-12-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'api_and_frontend' })
  kind: 'app,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${apiIdentity.id}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.13'
      appCommandLine: 'gunicorn --config gunicorn.conf.py "api.main:create_app()"'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
  }
}

resource appSettings 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: app
  name: 'appsettings'
  properties: union(
    toObject(env, setting => setting.name, setting => setting.value),
    {
      SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
      ENABLE_ORYX_BUILD: 'true'
    }
  )
}

resource logs 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: app
  name: 'logs'
  properties: {
    applicationLogs: {
      fileSystem: {
        level: 'Information'
      }
    }
    httpLogs: {
      fileSystem: {
        enabled: true
        retentionInDays: 3
        retentionInMb: 35
      }
    }
  }
}


output SERVICE_API_IDENTITY_PRINCIPAL_ID string = apiIdentity.properties.principalId
output SERVICE_API_NAME string = app.name
output SERVICE_API_URI string = 'https://${app.properties.defaultHostName}'
output APP_SERVICE_PLAN_NAME string = plan.name
