"""0.1 pagination, API keys and role hierarchy over HTTP on the dev server and generated FastAPI."""

import pytest
from starlette.testclient import TestClient

from tests.integration.support.v01_platform import EXPECTED, SPEC, exercise
from tests.unit.support.generated_apps import run_generated, write_spec
from yaml_api_generator.server import build_app

pytestmark = pytest.mark.integration


def test_dev_server(tmp_path, monkeypatch, mongo_uri, mongo_database):
    monkeypatch.setenv("YAML_API_MONGO_URI", mongo_uri)
    monkeypatch.setenv("YAML_API_MONGO_DB", mongo_database)
    spec = write_spec(tmp_path, SPEC.format(uri=mongo_uri, database=mongo_database))
    with TestClient(build_app(str(spec))) as client:
        assert exercise(client, mongo_uri, mongo_database) == EXPECTED


def test_generated_fastapi(tmp_path, mongo_uri, mongo_database):
    spec = write_spec(tmp_path, SPEC.format(uri=mongo_uri, database=mongo_database))
    script = f"""
    from tests.integration.support.v01_platform import exercise

    with client:
        print(json.dumps(exercise(client, {mongo_uri!r}, {mongo_database!r})))
    """
    env = {"MONGO_URI": mongo_uri, "MONGO_DB": mongo_database}
    assert run_generated(spec, "fastapi", script, env) == EXPECTED
