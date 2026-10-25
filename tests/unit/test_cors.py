"""CORS configuration of every spec version answers preflights in every consumer."""

import pytest
from starlette.testclient import TestClient

from tests.unit.support.generated_apps import generate, run_generated, write_spec
from tests.unit.support.http_probes import preflight
from yaml_api_generator.server import build_app, build_raw_app

ORIGIN = "https://app.example"
FOREIGN = "https://evil.example"
VERSIONS = ["0.1", "0.2", "0.3"]

_V01 = """
version: "0.1"
{cors}
collections:
  posts:
    fields:
      id: {{ type: id }}
      title: {{ type: string }}
"""

_V02_V03 = """
version: "{version}"
api:
  basePath: /api
  {cors}
mongo: {{ uri: "mongodb://localhost:27017", database: cors }}
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
"""

_CORS = {
    "0.1": "security: {{ cors: {{ allowedOrigins: [{origins}], allowedMethods: [GET, POST], allowCredentials: {credentials} }} }}",
    **dict.fromkeys(
        ("0.2", "0.3"), "cors: {{ origins: [{origins}], methods: [GET, POST], credentials: {credentials} }}"
    ),
}


def _spec(version: str, origin: str | None = ORIGIN, credentials: bool = True) -> str:
    cors = "" if origin is None else _CORS[version].format(
        origins=f'"{origin}"', credentials=str(credentials).lower()
    )
    return (_V01 if version == "0.1" else _V02_V03).format(version=version, cors=cors)


ALLOWED = {"status": 200, "origin": ORIGIN, "credentials": "true", "methods": "GET, POST"}
REFUSED = {"status": 400, "origin": None, "credentials": "true", "methods": "GET, POST"}

_PROBE = f"""
from tests.unit.support.http_probes import preflight

print(json.dumps([preflight(client, {ORIGIN!r}), preflight(client, {FOREIGN!r})]))
"""


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["dev-fastapi", "dev-raw"])
def test_dev_server_answers_preflight(tmp_path, version, build):
    client = TestClient(build(str(write_spec(tmp_path, _spec(version)))))
    assert [preflight(client, ORIGIN), preflight(client, FOREIGN)] == [ALLOWED, REFUSED]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("target", ["fastapi", "raw"])
def test_generated_app_answers_preflight(tmp_path, version, target):
    assert run_generated(write_spec(tmp_path, _spec(version)), target, _PROBE) == [ALLOWED, REFUSED]


@pytest.mark.parametrize("version", VERSIONS)
def test_generated_drf_configures_cors_headers(tmp_path, version):
    backend = generate(write_spec(tmp_path, _spec(version)), "drf")
    settings = next(backend.glob("*/settings.py")).read_text()
    assert '"corsheaders"' in settings
    assert "api.cors.RequestedHeadersCorsMiddleware" in settings
    assert f"CORS_ALLOWED_ORIGINS = ['{ORIGIN}']" in settings
    assert "CORS_ALLOW_METHODS = ['GET', 'POST']" in settings
    assert "CORS_ALLOW_CREDENTIALS = True" in settings
    assert "django-cors-headers" in (backend / "requirements.txt").read_text()


@pytest.mark.parametrize("version", VERSIONS)
def test_generated_drf_allows_any_origin_for_wildcard(tmp_path, version):
    backend = generate(write_spec(tmp_path, _spec(version, origin="*", credentials=False)), "drf")
    settings = next(backend.glob("*/settings.py")).read_text()
    assert "CORS_ALLOW_ALL_ORIGINS = True" in settings
    assert "CORS_ALLOWED_ORIGINS" not in settings


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("target", ["fastapi", "raw", "drf"])
def test_backend_without_cors_has_no_cors_layer(tmp_path, version, target):
    backend = generate(write_spec(tmp_path, _spec(version, origin=None)), target)
    assert not any("CorsMiddleware" in path.read_text() for path in backend.rglob("*.py"))


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["dev-fastapi", "dev-raw"])
def test_dev_server_without_cors_sends_no_cors_headers(tmp_path, version, build):
    client = TestClient(build(str(write_spec(tmp_path, _spec(version, origin=None)))))
    assert preflight(client, ORIGIN)["origin"] is None
