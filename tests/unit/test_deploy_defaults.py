"""deploy.port and deploy.mongo.local default from the rest of the spec and honour explicit values."""

import pytest

from tests.unit.support.generated_apps import write_spec
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
  runtime: docker
  {deploy}
"""

LOCAL_MONGO = 'mongo: { uri: "mongodb://localhost:27017", database: app }'
REMOTE_MONGO = 'mongo: { uri: "mongodb://db.example.com:27017", database: app }'
POSTGRES = 'datastores:\n  main: { type: postgres, dsn: "postgresql+asyncpg://db.example.com/app", default: true }'

_VERSIONS = pytest.mark.parametrize("version", ["0.2", "0.3"])


def _deploy_context(tmp_path, version: str, store: str, api: str = "", deploy: str = ""):
    spec = write_spec(tmp_path, _SPEC.format(version=version, api=api, store=store, deploy=deploy))
    return build_deploy_context(load_and_generate_ir(str(spec)).ir, "localhost", "ubuntu", "~/.ssh/id_rsa")


@_VERSIONS
@pytest.mark.parametrize(
    ("store", "deploy", "local"),
    [
        (LOCAL_MONGO, "", True),
        (REMOTE_MONGO, "", False),
        (POSTGRES, "", False),
        (REMOTE_MONGO, "mongo: { local: true }", True),
        (LOCAL_MONGO, "mongo: { local: false }", False),
    ],
    ids=["local-uri", "remote-uri", "postgres-only", "explicit-local", "explicit-remote"],
)
def test_mongo_local(tmp_path, version, store, deploy, local):
    context = _deploy_context(tmp_path, version, store, deploy=deploy)
    assert context.mongo_local is local
    assert [ds.local for ds in context.datastores if ds.type == "mongodb"] == ([local] if "mongo:" in store else [])


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
