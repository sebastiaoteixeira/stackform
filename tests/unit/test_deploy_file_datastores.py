"""Deploy bundles provision the file datastores of the generated app."""

import textwrap
from dataclasses import replace

import pytest
import yaml

from yaml_api_generator.generators.deploy.context_builder import build_deploy_context
from yaml_api_generator.generators.deploy.docker.generator import DockerDeployGenerator
from yaml_api_generator.ir import IRDeploy
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

_SPEC = """
version: "0.3"
api: {{ basePath: /api, version: v1 }}
datastores:
  store: {{ type: postgres, dsn: "postgresql+asyncpg://localhost/docs", default: true }}
  uploads: {{ type: filesystem, path: ./data/uploads }}
{stores}
entities:
  document:
    fields:
      id: {{ type: id }}
      cover: {{ type: file }}
{entities}
repositories:
  documents: {{ entity: document, files: uploads }}
{repositories}
services:
  documents: {{ repository: documents }}
controllers:
  documents:
    base_path: /documents
    routes:
      get: {{ service: documents, method: GET, path: "/{{id}}", access: public }}
"""


def _ir(tmp_path, runtime="docker", stores="", entities="", repositories=""):
    path = tmp_path / "spec.yaml"
    path.write_text(_SPEC.format(stores=stores, entities=entities, repositories=repositories))
    ir = load_and_generate_ir(str(path)).ir
    return replace(ir, deploy=IRDeploy(runtime=runtime))


def _media(name, endpoint):
    return {
        "stores": textwrap.indent(f'{name}: {{ type: s3, bucket: {name}, endpoint: "{endpoint}" }}', "  "),
        "entities": textwrap.indent(f"{name}_doc:\n  fields:\n    id: {{ type: id }}\n    scan: {{ type: file }}", "  "),
        "repositories": textwrap.indent(f"{name}_docs: {{ entity: {name}_doc, files: {name} }}", "  "),
    }


def _compose(tmp_path, ir):
    out = tmp_path / "deploy"
    DockerDeployGenerator().generate(build_deploy_context(ir, "localhost", "ubuntu", "~/.ssh/id"), out, tmp_path)
    return yaml.safe_load((out / "docker-compose.yml").read_text())


def test_filesystem_store_mounts_a_named_volume(tmp_path):
    compose = _compose(tmp_path, _ir(tmp_path))

    app = compose["services"]["app"]
    assert "files_uploads:/data/files/uploads" in app["volumes"]
    assert "FILES_UPLOADS_PATH=${FILES_UPLOADS_PATH:-/data/files/uploads}" in app["environment"]
    assert "files_uploads" in compose["volumes"]
    assert "minio" not in compose["services"]


def test_local_s3_store_runs_minio(tmp_path):
    compose = _compose(tmp_path, _ir(tmp_path, **_media("media", "http://localhost:9000")))

    minio = compose["services"]["minio"]
    assert minio["image"] == "minio/minio" and minio["command"] == "server /data"
    assert "MINIO_ROOT_USER=${FILES_MEDIA_ACCESS_KEY:-minioadmin}" in minio["environment"]
    assert "minio_data:/data" in minio["volumes"]
    app = compose["services"]["app"]
    assert "minio" in app["depends_on"]
    environment = app["environment"]
    assert "FILES_MEDIA_ENDPOINT=${FILES_MEDIA_ENDPOINT:-http://minio:9000}" in environment
    assert "FILES_MEDIA_CREATE_BUCKET=${FILES_MEDIA_CREATE_BUCKET:-true}" in environment
    assert [line for line in environment if line.startswith("FILES_MEDIA_ACCESS_KEY=")] == [
        "FILES_MEDIA_ACCESS_KEY=${FILES_MEDIA_ACCESS_KEY:-minioadmin}"
    ]
    assert "minio_data" in compose["volumes"]


def test_remote_s3_store_adds_no_service(tmp_path):
    compose = _compose(tmp_path, _ir(tmp_path, **_media("media", "https://s3.eu-west-1.amazonaws.com")))

    assert "minio" not in compose["services"]
    environment = compose["services"]["app"]["environment"]
    assert "FILES_MEDIA_ACCESS_KEY=${FILES_MEDIA_ACCESS_KEY}" in environment
    assert not any(line.startswith("FILES_MEDIA_ENDPOINT=") for line in environment)


def test_systemd_gets_filesystem_path_env(tmp_path):
    ctx = build_deploy_context(_ir(tmp_path, runtime="systemd"), "localhost", "ubuntu", "~/.ssh/id")

    assert ctx.env_vars["FILES_UPLOADS_PATH"] == "./data/uploads"


@pytest.mark.parametrize("names", [("media", "archive")])
def test_several_local_s3_stores_get_one_minio_each(tmp_path, names):
    parts = [_media(name, "http://127.0.0.1:9000") for name in names]
    sections = {key: "\n".join(part[key] for part in parts) for key in parts[0]}
    compose = _compose(tmp_path, _ir(tmp_path, **sections))

    assert {"minio-media", "minio-archive"} <= set(compose["services"])
    assert "FILES_ARCHIVE_ENDPOINT=${FILES_ARCHIVE_ENDPOINT:-http://minio-archive:9000}" in compose["services"]["app"]["environment"]
