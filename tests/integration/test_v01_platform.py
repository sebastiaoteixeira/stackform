"""0.1 pagination, credentialed CORS, API keys, credential storage and role hierarchy over HTTP on every server and target."""

import pytest
from starlette.testclient import TestClient

from tests.integration.support.v01_platform import EXPECTED, SPEC, exercise
from tests.unit.support.generated_apps import run_generated, write_spec
from yaml_api_generator.server import build_app, build_raw_app

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["dev", "devraw"])
def test_dev_server(build, tmp_path, monkeypatch, mongo_uri, mongo_database):
    monkeypatch.setenv("YAML_API_MONGO_URI", mongo_uri)
    monkeypatch.setenv("YAML_API_MONGO_DB", mongo_database)
    spec = write_spec(tmp_path, SPEC.format(uri=mongo_uri, database=mongo_database))
    with TestClient(build(str(spec))) as client:
        assert exercise(client, mongo_uri, mongo_database) == EXPECTED


@pytest.mark.parametrize("target", ["fastapi", "raw", "drf"])
def test_generated(target, tmp_path, mongo_uri, mongo_database):
    spec = write_spec(tmp_path, SPEC.format(uri=mongo_uri, database=mongo_database))
    script = f"""
    from tests.integration.support.v01_platform import exercise

    with client:
        print(json.dumps(exercise(client, {mongo_uri!r}, {mongo_database!r})))
    """
    env = {"MONGO_URI": mongo_uri, "MONGO_DB": mongo_database, "DJANGO_SECRET_KEY": "test-secret", "JWT_SECRET": "test-jwt-secret-0123456789abcdef0123456789"}
    assert run_generated(spec, target, script, env) == EXPECTED
