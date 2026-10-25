"""Development servers and a generated FastAPI app validate the shared payload scenario against a real PostgreSQL."""

import os

import pytest
from starlette.testclient import TestClient

from tests.integration.support.postgres import fresh_database
from tests.unit.support.scenarios import run_generated
from tests.unit.support import payload_requests
from tests.unit.support.payload_requests import EXPECTED, JWT_SECRET, SQL_STORE, scenario, spec
from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.server import build_app, build_raw_app


@pytest.fixture
def spec_file(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text(spec(SQL_STORE))
    return path


@pytest.mark.integration
@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["fastapi", "raw"])
def test_dev_server_validates_payloads(spec_file, build, postgres_uri, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    with fresh_database(postgres_uri) as dsn:
        monkeypatch.setenv("YAML_API_DB_STORE_DSN", dsn)
        with TestClient(build(str(spec_file))) as client:
            assert scenario(client) == EXPECTED


@pytest.mark.integration
def test_generated_fastapi_validates_payloads(spec_file, tmp_path, postgres_uri):
    compile_project(yaml_file=str(spec_file), output_dir=str(tmp_path / "fastapi"), target="fastapi")
    with fresh_database(postgres_uri) as dsn:
        env = {**os.environ, "DATABASE_URL": dsn, "JWT_SECRET": JWT_SECRET}
        assert run_generated(tmp_path / "fastapi" / "backend", payload_requests.__name__, env) == EXPECTED
