# Deployment Guide: Azure App Service

This adaptation keeps the upstream chat UI, FastAPI backend, Foundry project and
models, managed identity, sample RAG data, and optional tracing. Only application
hosting changes: a Linux App Service plan runs the built-in Python 3.13 runtime.
There is no custom container image, Docker build, Container Apps environment, or
container registry. App Service manages its own runtime internally.

## Prerequisites

- An Azure subscription and a region supporting App Service, Foundry, the chosen
  chat model, and optionally Azure AI Search.
- Subscription permissions to create resources and role assignments (typically
  Owner, or Contributor plus Role Based Access Control Administrator).
- Model quota: the deployment defaults are 80k tokens/minute for gpt-5.4-mini and,
  when RAG is enabled, 50k for text-embedding-3-small.
- Python 3.13, Node.js 22 LTS with npm, Azure CLI, and Azure Developer CLI
  (`azd` >= 1.14).
- PowerShell 7 (`pwsh`) on Windows.

Docker and a global pnpm installation are not required. The packaging hook runs
the frontend's pinned pnpm 10.6.0 through `npx`, so package-feed access is needed.
Optional upstream dev-container files are development tooling, not a deployment
dependency. Do not use `azd init -t get-started-with-ai-chat` or upstream Codespaces
buttons to obtain this adaptation: they fetch the original Container Apps version.

## Deploy from this folder

For Azure DevOps or GitHub Actions deployments without Azure Developer CLI, use the
[two-stage CI/CD guide](cicd.md). The local workflow below remains available.

On Windows:

```powershell
cd C:\FoundryStarter
azd auth login
azd up
```

Choose an environment name, subscription, and region. Open the HTTPS endpoint
printed by `azd`. The App Service plan defaults to B1 and is billed even when idle.
See [deployment customization](deploy_customization.md) for model settings,
existing Foundry projects, and optional resources.

### What deployment does

1. Bicep provisions Foundry, its project and chat model, storage, a user-assigned
   managed identity, a Linux App Service plan, and a web app. Search and monitoring
   retain their upstream feature flags and role assignments.
2. The service's `prepackage` hook installs frontend dependencies using the lockfile,
   builds React, and stages `src/.appservice`. This includes Python code, templates,
   static assets, sample embeddings, `gunicorn.conf.py`, `requirements.txt`, and
   `.deployment`, which explicitly enables dependency building for the ZIP.
   Frontend source, node_modules, local environments, and `.env` files are not staged.
3. `azd` ZIP-deploys the staged files to App Service. Oryx installs the Python
   dependencies remotely (`SCM_DO_BUILD_DURING_DEPLOYMENT=true`).
4. App Service starts `gunicorn --config gunicorn.conf.py "api.main:create_app()"`.
   Gunicorn uses Uvicorn workers and listens on port 8000 (or `PORT` if provided).
   The same backend serves React and streams `/chat` responses.
5. The application's `ManagedIdentityCredential` uses the web app's user-assigned
   identity through `AZURE_CLIENT_ID`; no model API keys are needed.

To rebuild and redeploy code, run `azd deploy`. To apply infrastructure or app
setting changes, run `azd provision` followed by `azd deploy`, or run `azd up`.
`azd deploy` alone does not update Bicep-managed settings.

## Optional RAG and tracing

Before deploying:

```powershell
azd env set USE_AZURE_AI_SEARCH_SERVICE true
azd env set ENABLE_AZURE_MONITOR_TRACING true
azd up
```

RAG retains the upstream sample embeddings and search behavior. Gunicorn's master
startup hook seeds a newly created search index; existing indexes are reused.
App Service restarts and scale-out therefore do not intentionally overwrite data.
See [RAG](RAG.md) and [monitoring](other_features.md).

When bringing an existing Foundry project, the upstream behavior is retained:
Search and Application Insights are not created. Configure the existing project's
monitoring connection before enabling tracing.

## Authentication

The demo is publicly accessible unless authentication is configured.
For an exposed deployment, use [Microsoft Entra authentication in App Service](azure_app_service_auth_setup.md).
This is separate from the managed identity used for backend resource access.

For optional demonstration-only HTTP Basic authentication:

```powershell
.\scripts\setup_credential.ps1
```

On Linux/macOS:

```bash
bash scripts/setup_credential.sh
```

These scripts set `WEB_APP_USERNAME` and `WEB_APP_PASSWORD` as App Service app
settings and restart the web app. Settings are encrypted by App Service, but
authorized administrators can read them; this is not a Key Vault integration.
Credentials are passed through a temporary JSON file, not echoed in CLI output.
Re-run the helper after `azd provision`/`azd up`, which replace the Bicep-managed
app settings. Code-only `azd deploy` preserves them. Do not combine Basic auth with
Entra authentication unless two independent authentication challenges are intended.

## Local development

See [the local development guide](local_development.md). From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r src\requirements.txt
python scripts\package_app.py
.\scripts\write_env.ps1
cd src
python -m uvicorn api.main:create_app --factory --reload
```

Sign in with `azd auth login` and ensure the deployed Foundry project is available.
The environment-writing script creates `src/.env` from `azd` outputs.
On Linux/macOS, use `python3`, activate `.venv/bin/activate`, and run
`bash scripts/write_env.sh`. Gunicorn is used only on Linux hosting; local Windows
development uses Uvicorn.

## Troubleshooting and cleanup

Check **App Service > Deployment Center > Logs** for Oryx installation failures
and **App Service > Monitoring > Log stream** for startup or request errors.
For recent RBAC assignments, allow time for permissions to propagate and restart.
See [troubleshooting](troubleshooting.md) for more checks.

```powershell
azd show
azd deploy --debug
azd down
```

`azd down` removes the environment resources, including the billed App Service plan.
It does not delete a Foundry project supplied as an existing resource.

## Offline validation

After installing development dependencies and building the package:

```powershell
python -m pip install -r requirements-dev.txt
python scripts\package_app.py
az bicep build --file infra\main.bicep --outfile infra\main.json
python -m unittest discover -s tests -p test_app_service.py -v
python -m ruff check scripts\package_app.py tests\test_app_service.py
azd package --all --no-prompt
```

These checks validate native hosting configuration, deployment contents, React assets,
streaming responses, optional Basic auth, and RAG seeding without making model calls.
They do not replace deployment and an end-to-end chat test against your Azure resources.
