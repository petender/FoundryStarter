import configparser
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api import main, routes  # noqa: E402


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestHostingContract(unittest.TestCase):
    def test_azd_and_parameter_contract(self):
        config = yaml.safe_load((ROOT / "azure.yaml").read_text())
        service = config["services"]["api_and_frontend"]
        self.assertEqual(service["host"], "appservice")
        self.assertEqual(service["dist"], ".appservice")
        self.assertNotIn("docker", service)
        for platform in ("windows", "posix"):
            self.assertIn("../scripts/package_app.py", service["hooks"]["prepackage"][platform]["run"])
            self.assertFalse(service["hooks"]["prepackage"][platform]["continueOnError"])

        template = json.loads((ROOT / "infra" / "main.json").read_text())
        parameters = json.loads((ROOT / "infra" / "main.parameters.json").read_text())["parameters"]
        self.assertFalse(set(parameters) - set(template["parameters"]))
        self.assertEqual(parameters["appServiceSku"]["value"], "${AZURE_APP_SERVICE_SKU=B1}")
        self.assertNotIn("containerRegistryName", parameters)

    def test_compiled_resources_use_native_python_and_identity(self):
        template = json.loads((ROOT / "infra" / "main.json").read_text())

        def resources(document):
            children = document.get("resources", [])
            if isinstance(children, dict):
                children = children.values()
            for resource in children:
                yield resource
                if resource["type"] == "Microsoft.Resources/deployments":
                    yield from resources(resource["properties"].get("template", {}))

        deployed = list(resources(template))
        types = {resource["type"] for resource in deployed}
        self.assertIn("Microsoft.Web/serverfarms", types)
        self.assertIn("Microsoft.Web/sites", types)
        self.assertFalse(any(t.startswith(("Microsoft.App/", "Microsoft.ContainerRegistry/")) for t in types))
        app = next(resource for resource in deployed if resource["type"] == "Microsoft.Web/sites")
        site = app["properties"]["siteConfig"]
        self.assertEqual(site["linuxFxVersion"], "PYTHON|3.13")
        self.assertEqual(site["appCommandLine"], 'gunicorn --config gunicorn.conf.py "api.main:create_app()"')
        self.assertTrue(site["alwaysOn"])
        self.assertTrue(app["properties"]["httpsOnly"])
        self.assertEqual(app["identity"]["type"], "UserAssigned")
        settings = next(r for r in deployed if r["type"] == "Microsoft.Web/sites/config"
                        and "'appsettings'" in r["name"])
        self.assertIn("SCM_DO_BUILD_DURING_DEPLOYMENT", settings["properties"])
        self.assertNotIn("WEBSITE_RUN_FROM_PACKAGE", settings["properties"])
        self.assertIn("SERVICE_API_NAME", template["outputs"])
        self.assertNotIn("AZURE_CONTAINER_REGISTRY_ENDPOINT", template["outputs"])


class TestPackaging(unittest.TestCase):
    def setUp(self):
        self.script = load_script("package_app", ROOT / "scripts" / "package_app.py")

    def test_stage_includes_runtime_files_but_not_local_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src"
            api = source / "api"
            assets = api / "static" / "react" / "assets"
            assets.mkdir(parents=True)
            (source / "frontend").mkdir()
            for name in ("main-react-app.js", "main-react-app.css"):
                (assets / name).write_text("built asset")
            (api / ".env").write_text("not-for-deployment")
            (api / "__pycache__").mkdir()
            (api / "__pycache__" / "main.pyc").write_text("bytecode")
            (api / "main.py").write_text("application")
            (api / "templates").mkdir()
            (api / "templates" / "index.html").write_text("template")
            (api / "data").mkdir()
            (api / "data" / "embeddings.csv").write_text("sample data")
            for name in ("requirements.txt", "gunicorn.conf.py"):
                (source / name).write_text("runtime")
            (source / ".deployment").write_text("[config]\nSCM_DO_BUILD_DURING_DEPLOYMENT = true\n")
            (root / "LICENSE").write_text("license")
            package = source / ".appservice"
            package.mkdir()
            (package / "stale.txt").write_text("old deployment")
            with patch.multiple(self.script, ROOT=root, SOURCE=source, PACKAGE=package), \
                    patch.object(self.script.shutil, "which", return_value="npx"), \
                    patch.object(self.script.subprocess, "run") as run:
                self.script.main()
            self.assertEqual(run.call_count, 2)
            self.assertIn("--frozen-lockfile", run.call_args_list[0].args[0])
            self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))
            self.assertTrue((package / "api" / "static" / "react" / "assets" / "main-react-app.js").is_file())
            self.assertTrue((package / "api" / "templates" / "index.html").is_file())
            self.assertTrue((package / "api" / "data" / "embeddings.csv").is_file())
            self.assertTrue((package / "requirements.txt").is_file())
            deployment = configparser.ConfigParser()
            deployment.read(package / ".deployment")
            self.assertTrue(deployment.getboolean("config", "SCM_DO_BUILD_DURING_DEPLOYMENT"))
            for excluded in ("api/.env", "api/__pycache__", "frontend", "stale.txt"):
                self.assertFalse((package / excluded).exists())

    def test_missing_node_is_an_explicit_error(self):
        with patch.object(self.script.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Node.js and npm are required"):
                self.script.main()

    def test_missing_assets_fail_before_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(self.script, "SOURCE", Path(directory)), \
                    patch.object(self.script.shutil, "which", return_value="npx"), \
                    patch.object(self.script.subprocess, "run"):
                with self.assertRaisesRegex(RuntimeError, "Frontend build did not produce"):
                    self.script.main()


class TestChatBehavior(unittest.TestCase):
    def setUp(self):
        self.cwd = Path.cwd()
        os.chdir(ROOT / "src" / ".appservice")
        self.environment = patch.dict(os.environ, {
            "RUNNING_IN_PRODUCTION": "true",
            "AZURE_CLIENT_ID": "test-managed-identity",
            "AZURE_EXISTING_AIPROJECT_ENDPOINT": "https://sample.services.ai.azure.com/api/projects/sample",
            "AZURE_AI_CHAT_DEPLOYMENT_NAME": "gpt-5.4-mini",
            "AZURE_AI_SEARCH_ENDPOINT": "",
            "ENABLE_AZURE_MONITOR_TRACING": "false",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(os.chdir, self.cwd)

    def test_ui_static_assets_and_streamed_chat(self):
        chat = AsyncMock()

        async def events():
            for content in ("Hello", " world"):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])

        chat.complete.return_value = events()
        with patch.object(main, "AIProjectClient", return_value=AsyncMock()), \
                patch.object(main, "ManagedIdentityCredential") as credential, \
                patch.object(main, "ChatCompletionsClient", return_value=chat), \
                patch.object(main, "EmbeddingsClient", return_value=AsyncMock()):
            with TestClient(main.create_app()) as client:
                home = client.get("/")
                self.assertEqual(home.status_code, 200)
                self.assertIn("<title>FoundryStarter | Sample AI Chat</title>", home.text)
                for name in ("main-react-app.js", "main-react-app.css"):
                    response = client.get(f"/static/react/assets/{name}")
                    self.assertEqual(response.status_code, 200)
                    self.assertGreater(len(response.content), 0)
                for name in ("azure-app-service.svg", "microsoft-foundry.svg", "github.svg", "azure-devops.svg"):
                    response = client.get(f"/static/assets/technology-icons/{name}")
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("image/svg+xml", response.headers["content-type"])
                    self.assertIn("<svg", response.text)
                    if name in ("azure-app-service.svg", "microsoft-foundry.svg"):
                        self.assertIn('viewBox="0 0 18 18"', response.text)
                        self.assertIn("<linearGradient", response.text)
                response = client.post("/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/event-stream", response.headers["content-type"])
                events_out = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
                self.assertEqual([event["type"] for event in events_out],
                                 ["message", "message", "completed_message", "stream_end"])
                self.assertEqual(events_out[2]["content"], "Hello world")
            credential.assert_called_once_with(client_id="test-managed-identity")
            self.assertEqual(chat.complete.call_args.kwargs["model"], "gpt-5.4-mini")
            self.assertTrue(chat.complete.call_args.kwargs["stream"])

    def test_optional_basic_auth_still_protects_chat_and_home(self):
        try:
            with patch.dict(os.environ, {"WEB_APP_USERNAME": "demo-user", "WEB_APP_PASSWORD": "demo-test-only"}), \
                    patch.object(main, "AIProjectClient", return_value=AsyncMock()), \
                    patch.object(main, "ManagedIdentityCredential"), \
                    patch.object(main, "ChatCompletionsClient", return_value=AsyncMock()), \
                    patch.object(main, "EmbeddingsClient", return_value=AsyncMock()):
                importlib.reload(routes)
                with TestClient(main.create_app()) as client:
                    for path in ("/", "/chat"):
                        request = client.get if path == "/" else client.post
                        arguments = {} if path == "/" else {"json": {"messages": [{"role": "user", "content": "Hi"}]}}
                        self.assertEqual(request(path, **arguments).status_code, 401)
                        self.assertEqual(request(path, auth=("demo-user", "wrong"), **arguments).status_code, 401)
                    self.assertEqual(client.get("/", auth=("demo-user", "demo-test-only")).status_code, 200)
        finally:
            importlib.reload(routes)

    def test_rag_and_tracing_remain_available(self):
        project = AsyncMock()
        project.telemetry.get_application_insights_connection_string.return_value = "mock-connection"
        search = AsyncMock()
        search.search.return_value = "sample knowledge"
        chat = AsyncMock()

        async def empty_stream():
            for event in ():
                yield event

        chat.complete.return_value = empty_stream()
        with patch.dict(os.environ, {
            "AZURE_AI_SEARCH_ENDPOINT": "https://sample.search.windows.net",
            "AZURE_AI_SEARCH_INDEX_NAME": "index_sample",
            "AZURE_AI_EMBED_DEPLOYMENT_NAME": "text-embedding-3-small",
            "AZURE_AI_EMBED_DIMENSIONS": "100",
            "ENABLE_AZURE_MONITOR_TRACING": "true",
        }), patch.object(main, "AIProjectClient", return_value=project), \
                patch.object(main, "ManagedIdentityCredential"), \
                patch.object(main, "ChatCompletionsClient", return_value=chat), \
                patch.object(main, "EmbeddingsClient", return_value=AsyncMock()), \
                patch.object(main, "SearchIndexManager", return_value=search), \
                patch("azure.monitor.opentelemetry.configure_azure_monitor") as monitor:
            with TestClient(main.create_app()) as client:
                response = client.post("/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
                self.assertEqual(response.status_code, 200)
                self.assertIn('"type": "stream_end"', response.text)
            monitor.assert_called_once_with(connection_string="mock-connection")
            search.ensure_index_created.assert_awaited_once_with(vector_index_dimensions=100)
            search.search.assert_awaited_once()
            self.assertIn("sample knowledge", chat.complete.call_args.kwargs["messages"][0]["content"])
            search.close.assert_awaited_once()


class TestGunicornStartup(unittest.IsolatedAsyncioTestCase):
    async def test_rag_seeds_only_a_new_index(self):
        config = load_script("gunicorn_config", ROOT / "src" / "gunicorn.conf.py")
        for created in (True, False):
            with self.subTest(created=created), patch.dict(os.environ, {
                "AZURE_AI_SEARCH_ENDPOINT": "https://sample.search.windows.net",
                "AZURE_AI_SEARCH_INDEX_NAME": "index_sample",
                "AZURE_AI_EMBED_DEPLOYMENT_NAME": "text-embedding-3-small",
                "AZURE_AI_EMBED_DIMENSIONS": "100",
            }), patch.object(config, "DefaultAzureCredential", return_value=AsyncMock()), \
                    patch("api.search_index_manager.SearchIndexManager") as manager:
                search = manager.return_value
                search.create_index = AsyncMock(return_value=created)
                search.upload_documents = AsyncMock()
                search.close = AsyncMock()
                await config.create_index_maybe()
                search.create_index.assert_awaited_once_with(vector_index_dimensions=100)
                self.assertEqual(search.upload_documents.await_count, int(created))

    async def test_no_search_does_not_initialize_rag(self):
        config = load_script("gunicorn_config_no_search", ROOT / "src" / "gunicorn.conf.py")
        with patch.dict(os.environ, {"AZURE_AI_SEARCH_ENDPOINT": ""}), \
                patch.object(config, "DefaultAzureCredential", return_value=AsyncMock()), \
                patch("api.search_index_manager.SearchIndexManager") as manager:
            await config.create_index_maybe()
            manager.assert_not_called()

    def test_port_and_worker_configuration(self):
        with patch.dict(os.environ, {"PORT": "8080", "WEB_CONCURRENCY": "1"}):
            config = load_script("gunicorn_config_custom", ROOT / "src" / "gunicorn.conf.py")
        self.assertEqual(config.bind, "0.0.0.0:8080")
        self.assertEqual(config.workers, 1)
        self.assertEqual(config.worker_class, "uvicorn.workers.UvicornWorker")


if __name__ == "__main__":
    unittest.main()
