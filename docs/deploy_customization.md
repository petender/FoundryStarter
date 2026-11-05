
# Getting Started with Chat Using Microsoft Foundry: Deployment customization

This document describes how to customize the deployment of the Agents Chat with Microsoft Foundry. Once you follow the steps here, you can run `azd up` as described in the section below.

* [Use existing resources](#use-existing-resources)
* [Enabling and disabling resources provision](#enabling-and-disabling-resources-provision)
* [Customizing resource names](#customizing-resource-names)
* [Customizing model deployments](#customizing-model-deployments)

## Use existing resources
Be default, this template provisions a new resource group along with other resources.   If you already have provisioned Microsoft Foundry and Microsoft Foundry Project (not a hub based project), you might reuse these resources by setting:

To find the value:

1. Open the azure portal
2. Navigate to the AI foundry resource
3. Select projects in the sidebar and open the desired project
4. Oo to 'Resource Management' -> 'Properties' in the sidebar
5. Copy the value from 'Resource ID'

```shell
azd env set AZURE_EXISTING_AIPROJECT_RESOURCE_ID "/subscriptions/<your-azure-subid>/resourceGroups/<your-rg>/providers/Microsoft.CognitiveServices/accounts/<your-ai-services-account-name>/projects/<your-project-name>"
```

Notices that Application Insight and AI Search will not be created in this scenario.


## Enabling and disabling resources provision

By default, provisioning Application Insights is enabled, and AI Search is disabled.  The default setting can be changed by:

* To enable AI Search, run `azd env set USE_AZURE_AI_SEARCH_SERVICE true`
* To disable Application Insights, run `azd env set USE_APPLICATION_INSIGHTS false`

Once you disable these resources, they will not be deployed when you run `azd up`.

## Customizing resource names

By default, this template will use a naming convention with unique strings to prevent naming collisions within Azure.
To override default naming conventions, the following keys can be set:

* `AZURE_AIPROJECT_NAME` - The name of the Microsoft Foundry project
* `AZURE_AISERVICES_NAME` - The name of the Microsoft Foundry
* `AZURE_STORAGE_ACCOUNT_NAME` - The name of the Storage Account
* `AZURE_APPLICATION_INSIGHTS_NAME` - The name of the Application Insights instance
* `AZURE_LOG_ANALYTICS_WORKSPACE_NAME` - The name of the Log Analytics workspace used by Application Insights
* `AZURE_APP_SERVICE_NAME` - The globally unique App Service web app name
* `AZURE_APP_SERVICE_PLAN_NAME` - The Linux App Service plan name

To override any of those resource names, run `azd env set <key> <value>` before running `azd up`.

### App Service plan

The default Linux plan is B1, with Always On enabled. To use a larger plan:

```shell
azd env set AZURE_APP_SERVICE_SKU S1
```

Use a Basic or higher SKU supporting Linux Python and Always On; Free/Shared
plans are not supported by this configuration. Unlike Container Apps consumption
hosting, the plan is billed continuously and does not scale to zero.
Changing settings after deployment requires `azd provision` (or `azd up`).

## Customizing model deployments

The default chat model is `gpt-5.4-mini`, version `2026-03-17`, using
`GlobalStandard`. This replaces the deprecated `gpt-4o-mini` snapshot; it is a
different model family, not a newer snapshot of that model. It supports the
sample's streaming Chat Completions API, but response behavior, latency, and
pricing can differ. Check [model availability](https://learn.microsoft.com/azure/ai-foundry/openai/concepts/models)
and quota in your deployment region.

Existing environment or pipeline variables override defaults. For an existing
Azure Developer CLI environment, update all three values before retrying:

```shell
azd env set AZURE_AI_CHAT_MODEL_NAME gpt-5.4-mini
azd env set AZURE_AI_CHAT_MODEL_VERSION 2026-03-17
azd env set AZURE_AI_CHAT_DEPLOYMENT_NAME gpt-5.4-mini
```

For the original Azure DevOps pipeline, update the corresponding pipeline
variables. For native CI/CD, use the model values in
[`infra/cicd.parameters.json`](../infra/cicd.parameters.json) and run a new CI build
before CD; a previously published artifact still contains the old model defaults.

For more information on the Azure OpenAI models and non-Microsoft models that can be used in your deployment, view the [list of models](https://learn.microsoft.com/azure/ai-services/agents/concepts/model-region-support).

To customize the model deployments, you can set the following environment variables:

### Using a different chat model

Change the chat model format (either OpenAI or Microsoft):

```shell
azd env set AZURE_AI_CHAT_MODEL_FORMAT Microsoft
```

Change the chat model name:

```shell
azd env set AZURE_AI_CHAT_MODEL_NAME gpt-5.4-mini
```

Set the version of the chat model:

```shell
azd env set AZURE_AI_CHAT_MODEL_VERSION 2026-03-17
```

### Setting models, capacity, and deployment SKU

By default, this template sets the chat model deployment capacity to 80,000 tokens per minute. For AI Search, the embedding model requires a capacity of 50,000 tokens per minute. Due to current Bicep limitations, only the chat model quota is validated when you select a location during `azd up`. If you want to change these defaults, set the desired region using `azd env set AZURE_LOCATION <region>` (for example, `eastus`) to bypass quota validation. Follow the instructions below to update the model settings before running `azd up`.

Change the default capacity (in thousands of tokens per minute) of the chat deployment:

```shell
azd env set AZURE_AI_CHAT_DEPLOYMENT_CAPACITY 50
```

Change the SKU of the chat deployment:

```shell
azd env set AZURE_AI_CHAT_DEPLOYMENT_SKU Standard
```

Change the default capacity (in thousands of tokens per minute) of the embeddings deployment:

```shell
azd env set AZURE_AI_EMBED_DEPLOYMENT_CAPACITY 50
```

Change the SKU of the embeddings deployment:

```shell
azd env set AZURE_AI_EMBED_DEPLOYMENT_SKU Standard
