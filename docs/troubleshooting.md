# Troubleshooting Guide

This guide provides solutions to common issues you may encounter when deploying and running the application.

## Provisioning and Deployment Failures

### Foundry project reports an existing resource or conflicting state

The high-level message can describe an operation conflict rather than a name
collision. Read the failed operation in the `cognitiveServices` deployment:

```powershell
az deployment operation group list --resource-group "<resource-group>" --name cognitiveServices --query "[?properties.provisioningState=='Failed'].properties.statusMessage" --output json
```

If the inner error is `RequestConflict` / "Another operation is in progress",
do not delete or purge the account. Foundry model, project, and connection writes
can contend for an account-level operation lock. The template serializes these
writes: account, model deployments, project, optional Application Insights
connection, then storage connection. Model deployments are also batched one at a time.
When Application Insights is disabled, storage still waits for project creation.

Wait for any previous deployment/account operation to finish, then retry
provisioning using the same environment and resource names. Do not run simultaneous
deployments against the same account. For native CI/CD, run a fresh CI build so
CD receives the corrected Bicep, rather than reusing an older artifact.

Only investigate soft-deleted resources when the inner error actually identifies
a deleted-resource/name conflict. Purging a resource is irreversible and is not
a remedy for `RequestConflict`.

### Resource Provisioning Issues

**Problem**: Timeouts or provisioning resources fail
**Solution**: 
- Change the location of your resource group, as there may be availability constraints for resources
- Call `azd down` and remove your current resources
- Delete the `.azure` folder from your workspace
- Call `azd up` again and select a different region

### Debugging Deployment Issues

**Debug Commands**:
- Use `azd show` to display information about your app and resources
- Use `azd deploy --debug` to enable debugging and logging while deploying the application's code to Azure

**General Checks**:
- Ensure that your `az` and `azd` tools are up to date
- After fully deploying with azd, additional errors in the Azure Portal may indicate that your latest code has not been successfully deployed

## Azure App Service

### Web App Startup Issues

**Problem**: The web app returns a startup error or does not load
**Possible Causes**: Deployment failure due to quota constraints, permission issues, or resource availability
**Solution**: Check **Deployment Center > Logs** for Oryx build failures and
**Monitoring > Log stream** for application errors.

- Confirm `linuxFxVersion` is `PYTHON|3.13`, and the startup command is
  `gunicorn --config gunicorn.conf.py "api.main:create_app()"`.
- Ensure `SCM_DO_BUILD_DURING_DEPLOYMENT` is `true`. Do not enable
  `WEBSITE_RUN_FROM_PACKAGE` for this Python remote-build deployment.
- Run `azd deploy` to rebuild and package React. A missing
  `/static/react/assets/main-react-app.js` indicates incomplete frontend packaging.
- Confirm the user-assigned identity is attached to the web app and `AZURE_CLIENT_ID`
  matches that identity. Newly assigned Foundry/Search roles can take time to propagate.
- Use `azd provision` before `azd deploy` when changing feature flags or app settings.

### HTTP 503 with `ModuleNotFoundError: No module named 'azure'`

If startup logs also show a missing `oryx-manifest.toml` or `antenv`, the application
ZIP was deployed without building its Python dependencies. A successful ZIP upload
does not prove that Oryx ran or that the application started.

The deployment package must contain `requirements.txt` and `.deployment` at its
root. `.deployment` explicitly sets `SCM_DO_BUILD_DURING_DEPLOYMENT=true` so the
ZIP requests a dependency build even on the first deployment. The web app also
retains its Bicep-managed remote-build settings.

Rebuild and redeploy the package, rather than just restarting the web app. In
Deployment Center logs, confirm that Oryx ran and installed the requirements.
Then verify the home page, static assets, and an actual `/chat` response.
Do not install dependencies from the startup command on every application restart.

### Logging and Debugging

**Console Traces**: 
- Can be found in the Azure Portal, but they may be unreliable
- Use Python's logging with INFO level
- Adjust Azure HTTP logging to WARNING

**Frontend Debugging**:
- Once your web app is deployed, utilize the browser debugger (F12)
- Clear cache (CTRL+SHIFT+R) to help debug the frontend for better traceability

## Getting Help

If you continue to experience issues after trying these solutions:

1. Check the [Microsoft Foundry documentation](https://learn.microsoft.com/azure/ai-foundry/)
2. Review the [App Service Python configuration and troubleshooting guide](https://learn.microsoft.com/azure/app-service/configure-language-python)
3. Consult the [Azure Developer CLI reference](https://learn.microsoft.com/azure/developer/azure-developer-cli/reference)
