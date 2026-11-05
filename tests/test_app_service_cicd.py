import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class TestPipelineContracts(unittest.TestCase):
    def setUp(self):
        self.azure = yaml.safe_load((ROOT / ".azdo" / "pipelines" / "azure-app-service.yml").read_text())
        self.github = yaml.safe_load((ROOT / ".github" / "workflows" / "app-service-cicd.yml").read_text())

    def test_azure_has_gated_ci_and_cd_with_native_zip_deployment(self):
        ci, cd = self.azure["stages"]
        self.assertEqual([ci["stage"], cd["stage"]], ["CI", "CD"])
        self.assertEqual(cd["dependsOn"], "CI")
        for gate in ("succeeded()", "'PullRequest'", "'refs/heads/main'", "'refs/heads/master'"):
            self.assertIn(gate, cd["condition"])
        ci_steps = ci["jobs"][0]["steps"]
        archive = next(step for step in ci_steps if step.get("task") == "ArchiveFiles@2")
        self.assertFalse(archive["inputs"]["includeRootFolder"])
        self.assertTrue(archive["inputs"]["rootFolderOrFile"].endswith("/src/.appservice"))
        publish = next(step for step in ci_steps if step.get("task") == "PublishPipelineArtifact@1")
        self.assertEqual(publish["inputs"]["artifact"], "app-service")
        cd_steps = cd["jobs"][0]["strategy"]["runOnce"]["deploy"]["steps"]
        download = next(step for step in cd_steps if step.get("task") == "DownloadPipelineArtifact@2")
        self.assertEqual(download["inputs"]["buildType"], "current")
        self.assertEqual(download["inputs"]["artifactName"], "app-service")
        deploy = next(step for step in cd_steps if step.get("task") == "AzureWebApp@1")
        self.assertEqual(deploy["inputs"]["appType"], "webAppLinux")
        self.assertEqual(deploy["inputs"]["deploymentMethod"], "zipDeploy")
        self.assertTrue(deploy["inputs"]["package"].endswith("/app.zip"))
        self.assertIn({"checkout": "none"}, cd_steps)

    def test_github_has_gated_ci_and_cd_with_oidc(self):
        jobs = self.github["jobs"]
        self.assertEqual(set(jobs), {"CI", "CD"})
        self.assertEqual(jobs["CD"]["needs"], "CI")
        self.assertNotIn("id-token", self.github["permissions"])
        self.assertEqual(jobs["CD"]["permissions"]["id-token"], "write")
        self.assertIn("github.event_name != 'pull_request'", jobs["CD"]["if"])
        self.assertIn("github.ref == 'refs/heads/main'", jobs["CD"]["if"])
        self.assertIn("github.ref == 'refs/heads/master'", jobs["CD"]["if"])
        self.assertFalse(jobs["CD"]["concurrency"]["cancel-in-progress"])
        steps = jobs["CD"]["steps"]
        login = next(step for step in steps if step.get("uses") == "azure/login@v2")
        self.assertNotIn("creds", login["with"])
        download = next(step for step in steps if step.get("uses") == "actions/download-artifact@v4")
        self.assertEqual(download["with"]["name"], "app-service")
        deploy = next(step for step in steps if step.get("uses") == "azure/webapps-deploy@v3")
        self.assertEqual(deploy["with"]["package"], "artifacts/app.zip")
        self.assertFalse(any(step.get("uses", "").startswith("actions/checkout@") for step in steps))

    def test_ci_validates_before_artifact_publication_and_cd_never_rebuilds(self):
        azure_steps = self.azure["stages"][0]["jobs"][0]["steps"]
        github_steps = self.github["jobs"]["CI"]["steps"]
        for steps, script_key, publish_action in (
            (azure_steps, "bash", "PublishPipelineArtifact@1"),
            (github_steps, "run", "actions/upload-artifact@v4"),
        ):
            validation = next(i for i, step in enumerate(steps) if "unittest" in step.get(script_key, ""))
            publish = next(i for i, step in enumerate(steps)
                           if step.get("task", step.get("uses")) == publish_action)
            self.assertLess(validation, publish)
            script = steps[validation][script_key]
            for check in ("package_app.py", "az bicep build", "ruff check", "compileall", "test_app_service*.py"):
                self.assertIn(check, script)
        for document in (self.azure, self.github):
            self.assertNotRegex(json.dumps(document), r"(?:^|\\n)\s*azd\s")
        for steps in (self.azure["stages"][1]["jobs"][0]["strategy"]["runOnce"]["deploy"]["steps"],
                      self.github["jobs"]["CD"]["steps"]):
            scripts = "\n".join(step.get("run", step.get("inputs", {}).get("inlineScript", "")) for step in steps)
            self.assertNotIn("package_app.py", scripts)
            self.assertNotIn("pip install", scripts)
            self.assertIn("deploy_infra.sh", scripts)

    def test_native_parameters_match_bicep_and_preserve_stable_naming(self):
        template = json.loads((ROOT / "infra" / "main.json").read_text())
        native = json.loads((ROOT / "infra" / "cicd.parameters.json").read_text())["parameters"]
        self.assertFalse(set(native) - set(template["parameters"]))
        self.assertEqual(native["principalType"]["value"], "ServicePrincipal")
        self.assertEqual(template["parameters"]["principalType"]["defaultValue"], "User")
        self.assertFalse(template["parameters"]["templateValidationMode"]["defaultValue"])
        self.assertEqual(template["parameters"]["principalType"]["allowedValues"], ["User", "ServicePrincipal"])
        self.assertEqual(native["aiSearchIndexName"]["value"], "index_sample")
        self.assertNotRegex(json.dumps(native), r"\$\{")
        self.assertNotIn("seed", native)
        helper = (ROOT / "scripts" / "deploy_infra.sh").read_text()
        self.assertIn("templateValidationMode=false", helper)
        self.assertIn("principalType=ServicePrincipal", helper)
        self.assertIn("az deployment sub create", helper)
        self.assertIsNone(re.search(r"(?m)^\s*azd\b", helper))

    def test_chat_model_defaults_match_across_deployment_paths(self):
        template = json.loads((ROOT / "infra" / "main.json").read_text())
        native = json.loads((ROOT / "infra" / "cicd.parameters.json").read_text())["parameters"]
        local = json.loads((ROOT / "infra" / "main.parameters.json").read_text())["parameters"]
        expected = {
            "chatModelName": ("AZURE_AI_CHAT_MODEL_NAME", "gpt-5.4-mini"),
            "chatModelVersion": ("AZURE_AI_CHAT_MODEL_VERSION", "2026-03-17"),
            "chatDeploymentName": ("AZURE_AI_CHAT_DEPLOYMENT_NAME", "gpt-5.4-mini"),
        }
        for parameter, (variable, value) in expected.items():
            with self.subTest(parameter=parameter):
                self.assertEqual(template["parameters"][parameter]["defaultValue"], value)
                self.assertEqual(native[parameter]["value"], value)
                self.assertEqual(local[parameter]["value"], "${" + variable + "=" + value + "}")
                for extension in ("ps1", "sh"):
                    script = (ROOT / "scripts" / f"set_default_models.{extension}").read_text(encoding="utf-8")
                    self.assertRegex(script, re.escape(variable) + r"[^\n]*" + re.escape(value))
        self.assertEqual(template["parameters"]["location"]["metadata"]["azd"]["usageName"],
                         ["OpenAI.GlobalStandard.gpt-5.4-mini,80"])
        original = yaml.safe_load((ROOT / ".azdo" / "pipelines" / "azure-dev.yml").read_text())
        provision = next(step for step in original["steps"] if step.get("displayName") == "Provision Infrastructure")
        self.assertEqual(provision["env"]["AZURE_AI_CHAT_MODEL_NAME"], "$(AZURE_AI_CHAT_MODEL_NAME)")

    def test_foundry_child_writes_are_serialized(self):
        template = json.loads((ROOT / "infra" / "main.json").read_text())
        ai = next(resource for resource in template["resources"] if resource["name"] == "ai")
        cognitive = next(resource for resource in ai["properties"]["template"]["resources"]
                         if resource["name"] == "cognitiveServices")
        resources = cognitive["properties"]["template"]["resources"]
        models = next(resource for resource in resources
                      if resource["type"] == "Microsoft.CognitiveServices/accounts/deployments")
        project = next(resource for resource in resources
                       if resource["type"] == "Microsoft.CognitiveServices/accounts/projects")
        connections = [resource for resource in resources
                       if resource["type"] == "Microsoft.CognitiveServices/accounts/connections"]
        insights = next(resource for resource in connections if "appInsightConnectionName" in resource["name"])
        storage = next(resource for resource in connections if "storageAccountConnectionName" in resource["name"])
        self.assertEqual(models["copy"]["mode"], "serial")
        self.assertEqual(models["copy"]["batchSize"], 1)
        self.assertIn(models["copy"]["name"], project["dependsOn"])
        self.assertTrue(any("aiProjectName" in dependency for dependency in insights["dependsOn"]))
        self.assertTrue(any("appInsightConnectionName" in dependency for dependency in storage["dependsOn"]))
        self.assertTrue(any("aiProjectName" in dependency for dependency in storage["dependsOn"]))
        self.assertIn("condition", insights)
        self.assertNotIn("condition", storage)


class TestInfrastructureDeploymentScript(unittest.TestCase):
    def setUp(self):
        self.bash = shutil.which("bash")
        if os.name == "nt" and (git := shutil.which("git")):
            git_bash = Path(git).parents[1] / "bin" / "bash.exe"
            if git_bash.is_file():
                self.bash = str(git_bash)
        if self.bash is None:
            self.skipTest("Bash is required for deployment-script tests.")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "infra").mkdir()
        for name in ("main.bicep", "cicd.parameters.json"):
            (self.root / "infra" / name).write_text("fixture")
        (self.root / "app.zip").write_bytes(b"fixture")
        self.outputs = {
            "AZURE_RESOURCE_GROUP": {"value": "rg-foundry-demo"},
            "SERVICE_API_NAME": {"value": "app-foundry-demo"},
            "SERVICE_API_URI": {"value": "https://app-foundry-demo.azurewebsites.net"},
        }
        (self.root / "response.json").write_text(json.dumps(self.outputs))
        self.env = dict(os.environ, DEPLOYMENT_ENVIRONMENT="foundry-demo", AZURE_LOCATION="eastus",
                        AZURE_DEPLOYMENT_PRINCIPAL_ID="11111111-2222-3333-4444-555555555555",
                        AZ_TEST_STATUS="0", JQ_TEST_STATUS="0",
                        AZ_TEST_ARGS=(self.root / "arguments.txt").as_posix(),
                        JQ_TEST_ARGS=(self.root / "jq-arguments.txt").as_posix(),
                        AZ_TEST_RESPONSE=(self.root / "response.json").as_posix())

    def run_script(self):
        harness = """
az() {
    printf '%s\\n' "$@" > "$AZ_TEST_ARGS"
    cat "$AZ_TEST_RESPONSE"
    return "$AZ_TEST_STATUS"
}
jq() {
    printf '%s\\n' "$@" > "$JQ_TEST_ARGS"
    return "$JQ_TEST_STATUS"
}
source "$1" "$2"
"""
        return subprocess.run(
            [self.bash, "-c", harness, "test", (ROOT / "scripts" / "deploy_infra.sh").as_posix(),
             self.root.as_posix()],
            env=self.env, capture_output=True, text=True, check=False,
        )

    def test_subscription_deployment_uses_verified_bicep_and_native_parameters(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = (self.root / "arguments.txt").read_text().splitlines()
        self.assertEqual(arguments[:3], ["deployment", "sub", "create"])
        resolved = subprocess.run(
            [self.bash, "-c", 'cd "$1" && pwd', "test", self.root.as_posix()],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(arguments[arguments.index("--template-file") + 1], resolved + "/infra/main.bicep")
        for value in ("environmentName=foundry-demo", "location=eastus",
                      "principalId=11111111-2222-3333-4444-555555555555",
                      "principalType=ServicePrincipal", "templateValidationMode=false"):
            self.assertIn(value, arguments)
        self.assertEqual(json.loads((self.root / "deployment-outputs.json").read_text()), self.outputs)
        self.assertIn(".SERVICE_API_NAME.value", (self.root / "jq-arguments.txt").read_text())

    def test_missing_or_invalid_principal_fails_before_any_azure_call(self):
        for principal in ("", "$(unsetPipelineVariable)", "not-an-object-id"):
            with self.subTest(principal=principal):
                self.env["AZURE_DEPLOYMENT_PRINCIPAL_ID"] = principal
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("AZURE_DEPLOYMENT_PRINCIPAL_ID", result.stderr)
                self.assertFalse((self.root / "arguments.txt").exists())

    def test_missing_artifact_fails_before_any_azure_call(self):
        (self.root / "app.zip").unlink()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Required CI artifact is missing", result.stderr)
        self.assertFalse((self.root / "arguments.txt").exists())

    def test_azure_failure_does_not_continue_to_output_extraction(self):
        self.env["AZ_TEST_STATUS"] = "17"
        result = self.run_script()
        self.assertEqual(result.returncode, 17)
        self.assertFalse((self.root / "jq-arguments.txt").exists())

    def test_output_extraction_failure_blocks_application_deployment(self):
        self.env["JQ_TEST_STATUS"] = "1"
        self.assertEqual(self.run_script().returncode, 1)


if __name__ == "__main__":
    unittest.main()
