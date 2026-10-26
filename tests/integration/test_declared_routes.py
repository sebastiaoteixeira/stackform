"""Register and login routes declared by a controller are served at their declared paths on every server and target."""

import pytest
from starlette.testclient import TestClient

from tests.integration.support.declared_routes import EXPECTED, SCENARIOS, exercise
from tests.unit.support.generated_apps import run_generated
from yaml_api_generator.server import build_app, build_raw_app

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=SCENARIOS.keys())
@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["dev", "devraw"])
def test_dev_server(scenario, build, tmp_path, monkeypatch, mongo_uri, mongo_database):
    monkeypatch.setenv("YAML_API_MONGO_URI", mongo_uri)
    monkeypatch.setenv("YAML_API_MONGO_DB", mongo_database)
    spec = scenario.materialize(tmp_path, mongo_uri, mongo_database)
    with TestClient(build(str(spec))) as client:
        assert exercise(client, scenario.prefix, scenario.profile) == EXPECTED


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=SCENARIOS.keys())
@pytest.mark.parametrize("target", ["fastapi", "raw", "drf"])
def test_generated(scenario, target, tmp_path, mongo_uri, mongo_database):
    spec = scenario.materialize(tmp_path, mongo_uri, mongo_database)
    script = f"""
    from tests.integration.support.declared_routes import exercise

    with client:
        print(json.dumps(exercise(client, {scenario.prefix!r}, {scenario.profile!r})))
    """
    env = {"MONGO_URI": mongo_uri, "MONGO_DB": mongo_database, "DJANGO_SECRET_KEY": "test-secret", "JWT_SECRET": "test-jwt-secret-0123456789abcdef0123456789"}
    assert run_generated(spec, target, script, env) == EXPECTED
