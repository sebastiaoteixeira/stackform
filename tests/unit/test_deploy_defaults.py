"""deploy.port and deploy.mongo.local default from the rest of the spec, honour explicit values and reach every bundle file."""

import pytest
import yaml
from click.testing import CliRunner

from tests.unit.support.generated_apps import write_spec
from yaml_api_generator.cli import cli
from yaml_api_generator.cli.compiler import backend_generator
from yaml_api_generator.generators.deploy.context_builder import build_deploy_context
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

_SPEC = """
version: "{version}"
api:
  basePath: /api
  {api}
{store}
entities:
  post:
    fields:
      id: {{ type: id }}
      title: {{ type: string }}
repositories:
  posts: {{ entity: post }}
services:
  posts: {{ repository: posts }}
controllers:
  posts:
    base_path: /posts
    routes:
      list: {{ service: posts, method: GET, path: "", access: public }}
deploy:
  runtime: {runtime}
  {deploy}
"""

LOCAL_MONGO = 'mongo: { uri: "mongodb://localhost:27017", database: app }'
REMOTE_MONGO = 'mongo: { uri: "mongodb://db.example.com:27017", database: app }'
POSTGRES = 'datastores:\n  main: { type: postgres, dsn: "postgresql+asyncpg://db.example.com/app", default: true }'

_VERSIONS = pytest.mark.parametrize("version", ["0.2", "0.3"])
_TARGETS = pytest.mark.parametrize("target", ["fastapi", "raw", "drf"])


def _spec(tmp_path, version: str, store: str, api: str = "", deploy: str = "", runtime: str = "docker"):
    return write_spec(tmp_path, _SPEC.format(version=version, api=api, store=store, deploy=deploy, runtime=runtime))


def _deploy_context(tmp_path, version: str, store: str, api: str = "", deploy: str = ""):
    ir = load_and_generate_ir(str(_spec(tmp_path, version, store, api, deploy))).ir
    return build_deploy_context(ir, "app:app", "localhost", "ubuntu", "~/.ssh/deploy")


def _bundle(tmp_path, spec, target: str = "fastapi"):
    output = tmp_path / "bundle"
    result = CliRunner().invoke(cli, ["build", str(spec), "deploy", "-o", str(output), "-t", target])
    assert result.exit_code == 0, result.output
    return output


@_VERSIONS
@pytest.mark.parametrize(
    ("store", "deploy", "local", "mongo_uri"),
    [
        (LOCAL_MONGO, "", True, "mongodb://mongodb:27017"),
        (REMOTE_MONGO, "", False, "mongodb://db.example.com:27017"),
        (POSTGRES, "", False, None),
        (REMOTE_MONGO, "mongo: { local: true }", True, "mongodb://mongodb:27017"),
        (LOCAL_MONGO, "mongo: { local: false }", False, "mongodb://localhost:27017"),
    ],
    ids=["local-uri", "remote-uri", "postgres-only", "explicit-local", "explicit-remote"],
)
def test_mongo_local(tmp_path, version, store, deploy, local, mongo_uri):
    context = _deploy_context(tmp_path, version, store, deploy=deploy)
    mongo = [ds for ds in context.datastores if ds.type == "mongodb"]
    assert context.local_mongo is local
    assert [(ds.local, ds.app_env["MONGO_URI"]) for ds in mongo] == ([(local, mongo_uri)] if mongo_uri else [])
    assert (f"MONGO_URI=${{MONGO_URI:-{mongo_uri}}}" in context.app_environment) is bool(mongo_uri)


@_VERSIONS
def test_remote_postgres_keeps_its_dsn(tmp_path, version):
    context = _deploy_context(tmp_path, version, POSTGRES)
    assert context.local_datastores == ()
    assert "DATABASE_URL=${DATABASE_URL:-postgresql+asyncpg://db.example.com/app}" in context.app_environment


@_VERSIONS
@pytest.mark.parametrize(
    ("api", "deploy", "port"),
    [("", "", 8000), ("port: 9100", "", 9100), ("port: 9100", "port: 9200", 9200)],
    ids=["default", "api-port", "deploy-port"],
)
def test_port(tmp_path, version, api, deploy, port):
    context = _deploy_context(tmp_path, version, LOCAL_MONGO, api=api, deploy=deploy)
    assert context.port == port
    assert f"PORT=${{PORT:-{port}}}" in context.app_environment


@_TARGETS
def test_docker_serves_target_application_on_port(tmp_path, target):
    bundle = _bundle(tmp_path, _spec(tmp_path, "0.3", REMOTE_MONGO, api="port: 9100"), target)
    dockerfile = (bundle / "backend" / "Dockerfile").read_text().splitlines()
    application = backend_generator(target).asgi_application
    assert "ENV PORT=9100" in dockerfile
    assert f'CMD exec uvicorn {application} --host 0.0.0.0 --port "$PORT"' in dockerfile


@_TARGETS
def test_systemd_serves_target_application_on_port(tmp_path, target):
    bundle = _bundle(tmp_path, _spec(tmp_path, "0.3", REMOTE_MONGO, api="port: 9100", runtime="systemd"), target)
    service = (bundle / "files" / "app.service").read_text().splitlines()
    application = backend_generator(target).asgi_application
    assert "Environment=PORT=9100" in service
    assert f"ExecStart=/opt/app/venv/bin/uvicorn {application} --host 0.0.0.0 --port ${{PORT}}" in service


@pytest.mark.parametrize(
    ("store", "deploy", "services"),
    [
        (LOCAL_MONGO, "", ["app", "mongodb"]),
        (LOCAL_MONGO, "mongo: { local: false }", ["app"]),
        (POSTGRES, "", ["app"]),
    ],
    ids=["local-mongo", "explicit-remote", "postgres-only"],
)
def test_docker_runs_local_stores_in_compose_and_installs_docker(tmp_path, store, deploy, services):
    bundle = _bundle(tmp_path, _spec(tmp_path, "0.3", store, deploy=deploy))
    assert list(yaml.safe_load((bundle / "docker-compose.yml").read_text())["services"]) == services
    assert yaml.safe_load((bundle / "playbook.yml").read_text())[0]["roles"] == ["docker", "app"]
    assert (bundle / "roles" / "docker" / "tasks" / "main.yml").exists()
    assert not (bundle / "roles" / "mongodb").exists()


@pytest.mark.parametrize(
    ("store", "deploy", "roles"),
    [
        (LOCAL_MONGO, "", ["mongodb", "python", "app"]),
        (REMOTE_MONGO, "mongo: { local: true }", ["mongodb", "python", "app"]),
        (LOCAL_MONGO, "mongo: { local: false }", ["python", "app"]),
        (POSTGRES, "", ["python", "app"]),
    ],
    ids=["local-uri", "explicit-local", "explicit-remote", "postgres-only"],
)
def test_systemd_installs_mongodb_only_for_a_local_mongo_store(tmp_path, store, deploy, roles):
    bundle = _bundle(tmp_path, _spec(tmp_path, "0.3", store, deploy=deploy, runtime="systemd"))
    assert yaml.safe_load((bundle / "playbook.yml").read_text())[0]["roles"] == roles
    assert (bundle / "roles" / "mongodb").exists() is ("mongodb" in roles)


def test_readme_describes_only_the_compose_services(tmp_path):
    bundle = _bundle(tmp_path, _spec(tmp_path, "0.3", POSTGRES))
    readme = (bundle / "README.md").read_text()
    assert "mongodb" not in readme.lower()
    assert "postgresql+asyncpg://db.example.com/app" in readme


@_VERSIONS
@pytest.mark.parametrize("runtime", ["docker", "systemd"])
@pytest.mark.parametrize("local", ["true", "false"])
def test_mongo_settings_without_a_mongo_store_rejected(tmp_path, version, runtime, local):
    spec = _spec(tmp_path, version, POSTGRES, deploy=f"mongo: {{ local: {local} }}", runtime=runtime)
    result = CliRunner().invoke(cli, ["build", str(spec), "deploy", "-o", str(tmp_path / "bundle")])
    assert result.exit_code != 0
    assert "deploy.mongo requires a MongoDB datastore" in result.output
    assert not (tmp_path / "bundle").exists()
