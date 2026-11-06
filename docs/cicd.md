# Two-stage CI/CD without Azure Developer CLI

These are alternative pipelines; the original development/deployment workflow
remains available. Neither new pipeline installs or executes Azure Developer CLI.

| Platform | Pipeline |
| --- | --- |
| Azure DevOps | [azure-app-service.yml](../.azdo/pipelines/azure-app-service.yml) |
| GitHub Actions | [app-service-cicd.yml](../.github/workflows/app-service-cicd.yml) |

Both use Ubuntu agents, Python 3.13, Node.js 22, Azure CLI, and native web-app
deployment tasks. CI needs no Azure login. CD authenticates with a deployment
service principal; the app itself still uses its separate managed identity.

For DevOps course labs, the chat UI's "Deployed by" badges link to the GitHub
Actions and Azure DevOps setup sections below. These are alternative learner
paths, not a claim that both pipelines deployed the running app. Choose one
pipeline for your workload; learners can enter their own chat questions.

## Stage 1: CI

For pull requests and pushes to `main`/`master`:

1. Install the existing development dependencies.
2. Build React and stage the Python application using [package_app.py](../scripts/package_app.py).
3. Compile Bicep, byte-compile Python, run Ruff and the offline application/pipeline
   tests, and check the infrastructure deployment script's Bash syntax.
4. ZIP the staged application with `api`, `requirements.txt`, and
   `gunicorn.conf.py` at the archive root, not under a parent directory. The ZIP
   also includes `.deployment` to explicitly request Kudu's remote dependency build.
5. Publish `app-service`: `app.zip`, the verified infrastructure sources and
   parameter file, and the infrastructure deployment script.

Publication occurs only after successful validation. The ZIP excludes frontend
source, node_modules, local virtual environments, and `.env` files.

## Stage 2: CD

CD depends on successful CI and runs only on `main`/`master`, never on pull requests.
GitHub manual dispatch also requires one of these deployment branches.

1. Download the artifact from the **same pipeline/workflow run**; do not check out
   newer source or rebuild the application.
2. Authenticate to Azure.
3. Run [deploy_infra.sh](../scripts/deploy_infra.sh), which uses
   `az deployment sub create` with the artifact's Bicep and native ARM parameter file.
   The template is subscription-scoped because it creates the resource group.
4. Read the resulting web-app name from the deployment outputs.
5. Deploy the exact CI ZIP using `AzureWebApp@1` (Azure DevOps) or
   `azure/webapps-deploy@v3` (GitHub Actions).

Bicep sets the built-in Python runtime, startup command, managed identity, and
`SCM_DO_BUILD_DURING_DEPLOYMENT=true`. App Service/Oryx installs Python dependencies
on deployment; frontend assets are already compiled. Do not enable
`WEBSITE_RUN_FROM_PACKAGE` or substitute a run-from-package deployment method:
this app requires Python remote build.

The pipeline deploys infrastructure on every CD run. Keep the environment name,
region, and explicit resource names stable to update the same resources.
`principalType=ServicePrincipal` is independent of `templateValidationMode`, which
is explicitly disabled: test mode would generate a new resource suffix each run.

## Azure permissions

The deployment identity needs permission to create subscription-scoped deployments,
resource groups and resources, and to assign roles. For a demonstration, use
subscription **Contributor** plus **Role Based Access Control Administrator**
(or Owner), subject to your organization's access policies.

The deployment principal ID must be the **object ID of the enterprise application /
service principal**, not the application/client ID, tenant ID, or app managed
identity ID. You can retrieve it after signing in interactively:

```powershell
az ad sp show --id "<deployment-application-client-id>" --query id --output tsv
```

If directory lookup is restricted, obtain the object ID from an Entra administrator.
The pipeline uses the configured object ID and does not require Graph lookup
permissions at runtime.

## Configure Azure DevOps

1. Create an Azure Resource Manager service connection named `foundry-app-service`,
   preferably using **workload identity federation**, targeting your subscription.
   Grant it the permissions above and authorize this pipeline to use it.
2. Create an Azure Pipelines pipeline pointing to
   [.azdo/pipelines/azure-app-service.yml](../.azdo/pipelines/azure-app-service.yml).
3. Edit its YAML variables:

   | Variable | Example / meaning |
   | --- | --- |
   | `azureServiceConnection` | `foundry-app-service`; your ARM service connection name |
   | `deploymentEnvironment` | `foundry-demo`; stable resource suffix and Azure DevOps environment |
   | `azureLocation` | `eastus`; region with model quota and App Service support |
   | `azureDeploymentPrincipalId` | Deployment service principal **object ID**; required, initially blank |

4. Create the Azure DevOps environment matching `deploymentEnvironment`. Configure
   approvals/checks on that environment if deployment requires approval.
5. For Azure Repos, add a **build validation branch policy** on `main`/`master`:
   YAML `pr` triggers apply to supported external repositories, not Azure Repos.
6. Run the pipeline. AzureCLI@2 provisions Bicep and exposes the resulting app name
   to AzureWebApp@1 for ZIP deployment.

Use one pipeline to deploy a given environment, or configure an Azure DevOps
environment exclusive lock/check if multiple deployment runs can overlap.

## Configure GitHub Actions

1. Create an Entra application/service principal, grant the Azure permissions above,
   and add a federated identity credential for your repository's GitHub environment.
   For the supplied workflow:
   - Issuer: `https://token.actions.githubusercontent.com`
   - Subject: `repo:<owner>/<repository>:environment:foundry-demo`
   - Audience: `api://AzureADTokenExchange`
2. Create a GitHub environment named `foundry-demo`. Configure required reviewers
   and restrict deployment branches to `main`/`master` as appropriate.
3. Configure these repository or environment **Actions variables**:

   | Variable | Meaning |
   | --- | --- |
   | `AZURE_CLIENT_ID` | Deployment application's client ID |
   | `AZURE_TENANT_ID` | Entra tenant ID |
   | `AZURE_SUBSCRIPTION_ID` | Target Azure subscription ID |
   | `AZURE_DEPLOYMENT_PRINCIPAL_ID` | Deployment service principal **object ID** |
   | `DEPLOYMENT_ENVIRONMENT` | Stable Bicep environment name, e.g. `foundry-demo` |
   | `AZURE_LOCATION` | Resource and subscription-deployment region, e.g. `eastus` |

4. Push the code and workflow to your GitHub repository. The workflow runs CI on
   pull requests, and CI followed by CD on deployment-branch pushes. You can also
   use **Actions > App Service CI/CD (without azd) > Run workflow**.

Only CD receives `id-token: write`; no client secret or publish profile is required.
The CD concurrency group serializes GitHub deployments and does not cancel an
active deployment. If you rename the GitHub environment, update both the workflow's
`environment` and the federated credential subject.

## Maintaining GitHub Actions

Dependabot proposes grouped action updates weekly. Review major-version release
notes and require the PR's CI checks to pass before merging. Pipeline contract
tests identify actions by repository name, so version bumps and commit-SHA pins
do not require changing the tests; artifact, deployment and OIDC checks remain
enforced.

The newer `actions/*` releases use the Node.js 24 action runtime, independently of the app's
Node.js 22 and Python 3.13 versions. GitHub-hosted Ubuntu runners support it;
self-hosted runners must be at least version 2.327.1. Automatic npm caching is
explicitly disabled. Upload keeps `archive: true` so the `app-service` artifact
contains both the unchanged `app.zip` and infrastructure files, and CD extracts
that bundle without rebuilding it.

Action updates do not configure workload identity federation or deployment
variables. PR CI needs neither; validating Azure login and deployment requires
the CD configuration above. The separate, manually dispatched Template
Validation workflow still uses its existing development tooling, not the native
App Service pipeline.

## Native deployment settings

Edit [infra/cicd.parameters.json](../infra/cicd.parameters.json) before committing.
It is a normal ARM parameter file with real JSON values, not environment-variable
substitution syntax. It intentionally does not use `infra/main.parameters.json`,
which is the original CLI's environment-expanded parameter file.

The initial chat model is `gpt-5.4-mini`, version `2026-03-17`, with a deployment
name of `gpt-5.4-mini`. The settings retain B1, optional Application Insights, disabled Search and
tracing, chat capacity 80, embedding capacity 50, and `index_sample` for optional RAG.
Set `useSearchService` to `true` to provision RAG. Enable tracing with
`enableAzureMonitorTracing=true` when monitoring is available.

Any other Bicep parameter can be added to this file, including explicit resource
names, model versions/capacities, and `azureExistingAIProjectResourceId`.
The deployment script always overrides environment, location, principal ID/type,
and test mode. Existing-project behavior is unchanged: this sample does not create
Search or Application Insights when bringing an existing Foundry project.
Model availability/quota is validated by Azure during deployment, not by a CLI
quota-selection wizard.

Use distinct environment names if Azure DevOps and GitHub should deploy separate
demo instances. If they deploy the same environment, their identities must both be
authorized; GitHub concurrency does not coordinate with Azure DevOps.

## Operational notes

- Configure [App Service Entra authentication](azure_app_service_auth_setup.md)
  before exposing the demo publicly.
- Bicep redeployment replaces app settings. Manually configured Basic-auth app
  settings must be reapplied after infrastructure deployment; Entra authentication
  is configured separately. The original Basic-auth helper scripts use the original
  CLI's local environment and are not called by these pipelines.
- Check App Service **Deployment Center > Logs** for Oryx/dependency errors, and
  **Monitoring > Log stream** for application startup or RBAC propagation failures.
- These pipelines compile and test locally but do not perform a real model request
  in CI. Test a chat response and optional RAG after the first Azure deployment.
- Only application **source and frontend assets** are promoted unchanged. Python
  dependencies are resolved from the existing requirements on each Oryx build;
  lock those dependencies separately if reproducible dependency resolution is required.
- To remove a pipeline-created environment without the original CLI, delete its
  resource group through the Azure portal or `az group delete`. Check the resource
  group name first and retain any externally supplied Foundry project.

## Local validation without Azure deployment

After activating a Python 3.13 environment:

```powershell
python -m pip install -r requirements-dev.txt
python scripts\package_app.py
az bicep build --file infra\main.bicep --outfile infra\main.json
python -m ruff check scripts\package_app.py tests\test_app_service*.py
python -m unittest discover -s tests -p "test_app_service*.py" -v
```

The deployment-script tests mock Azure CLI calls. They require Bash (Git Bash on
Windows) and do not provision resources.
