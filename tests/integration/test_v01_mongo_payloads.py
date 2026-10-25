"""A v0.1 spec serves and validates its collections on the development servers and the generated FastAPI and raw-ASGI apps."""

import os
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from tests.unit.support import v01_payload_requests
from tests.unit.support.scenarios import run_generated
from tests.unit.support.v01_payload_requests import EXPECTED, scenario, spec
from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.server import build_app, build_raw_app


@pytest.fixture
def spec_file(tmp_path, mongo_uri):
    path = tmp_path / "spec.yaml"
    path.write_text(spec(mongo_uri, f"v01_{uuid4().hex}"))
    return path


@pytest.mark.integration
@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["fastapi", "raw"])
def test_dev_server_serves_v01_collections(spec_file, build):
    with TestClient(build(str(spec_file))) as client:
        assert scenario(client) == EXPECTED


@pytest.mark.integration
@pytest.mark.parametrize("target", ["fastapi", "raw"])
def test_generated_backend_serves_v01_collections(spec_file, tmp_path, mongo_uri, target):
    compile_project(yaml_file=str(spec_file), output_dir=str(tmp_path / target), target=target)
    env = {**os.environ, "MONGO_URI": mongo_uri, "MONGO_DB": f"v01_{uuid4().hex}"}
    assert run_generated(tmp_path / target / "backend", v01_payload_requests.__name__, env) == EXPECTED
