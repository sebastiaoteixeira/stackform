"""session.ttl sets the access-token lifetime in the dev server and every generated backend."""

import pytest
from starlette.testclient import TestClient

from tests.unit.support.generated_apps import generate, run_generated
from tests.unit.support.http_probes import TOKEN_LIFETIME_PROBE, token_lifetime
from tests.unit.support.session_spec import LASTING, ROTATING, mongo, session_spec
from yaml_api_generator.server import build_app


def _cases(lifetimes: dict[str, int]):
    return pytest.mark.parametrize(
        ("session", "lifetime"), lifetimes.items(), ids=lambda value: str(value) or "none"
    )


_VERSIONS = pytest.mark.parametrize("version", ["0.2", "0.3"])


@_VERSIONS
@_cases(LASTING | ROTATING)
def test_dev_server_login_token_lifetime(tmp_path, monkeypatch, version, session, lifetime):
    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path / 'dev.db'}")
    with TestClient(build_app(str(session_spec(tmp_path, session, version)))) as client:
        assert token_lifetime(client) == lifetime


@_VERSIONS
@_cases(LASTING | ROTATING)
def test_generated_fastapi_login_token_lifetime(tmp_path, version, session, lifetime):
    database = {"DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'generated.db'}"}
    spec = session_spec(tmp_path, session, version)
    assert run_generated(spec, "fastapi", TOKEN_LIFETIME_PROBE, database) == lifetime


@_cases(ROTATING)
def test_generated_fastapi_settings_rotating_lifetime(tmp_path, session, lifetime):
    backend = generate(session_spec(tmp_path, session, store=mongo()), "fastapi")
    assert f"JWT_ACCESS_TTL_SECONDS: int = {lifetime}" in (backend / "settings.py").read_text()


@_cases(LASTING)
@pytest.mark.parametrize(("target", "settings"), [("raw", "settings.py"), ("drf", "api/settings.py")])
def test_generated_settings_lasting_lifetime(tmp_path, session, lifetime, target, settings):
    backend = generate(session_spec(tmp_path, session, store=mongo()), target)
    expected = f"JWT_ACCESS_TTL_SECONDS: int = {lifetime}" if session else "JWT_EXPIRATION_HOURS: int = 24"
    assert expected in (backend / settings).read_text()
