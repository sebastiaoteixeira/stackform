"""Standard security headers are on by default and every consumer honours the off switch."""

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from tests.unit.support.generated_apps import generate, run_generated, write_spec
from yaml_api_generator.runtime.security_headers import (
    STANDARD_HEADERS,
    DjangoSecurityHeadersMiddleware,
    SecurityHeadersMiddleware,
)
from yaml_api_generator.server import build_app, build_raw_app

_V01 = """
version: "0.1"
{switch}
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
  {switch}
mongo: {{ uri: "mongodb://localhost:27017", database: headers }}
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

_SPECS = {
    ("0.1", True): _V01.format(switch=""),
    ("0.1", False): _V01.format(switch="security: { headers: { enableStandard: false } }"),
    **{
        (version, enabled): _V02_V03.format(
            version=version, switch="" if enabled else "securityHeaders: false"
        )
        for version in ("0.2", "0.3")
        for enabled in (True, False)
    },
}

_CASES = pytest.mark.parametrize(
    ("version", "enabled"), sorted(_SPECS), ids=lambda value: str(value)
)

_PROBE = """
print(json.dumps(dict(client.get("/missing").headers)))
"""


def _standard_headers(headers) -> dict[str, str]:
    return {name: headers[name] for name, _ in STANDARD_HEADERS if name in headers}


def _expected(enabled: bool) -> dict[str, str]:
    return dict(STANDARD_HEADERS) if enabled else {}


@_CASES
@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["dev-fastapi", "dev-raw"])
def test_dev_server_response_headers(tmp_path, version, enabled, build):
    client = TestClient(build(str(write_spec(tmp_path, _SPECS[version, enabled]))))
    assert _standard_headers(client.get("/missing").headers) == _expected(enabled)


@_CASES
@pytest.mark.parametrize("target", ["fastapi", "raw"])
def test_generated_app_response_headers(tmp_path, version, enabled, target):
    headers = run_generated(write_spec(tmp_path, _SPECS[version, enabled]), target, _PROBE)
    assert _standard_headers(headers) == _expected(enabled)


@_CASES
def test_generated_drf_installs_middleware_only_when_enabled(tmp_path, version, enabled):
    backend = generate(write_spec(tmp_path, _SPECS[version, enabled]), "drf")
    settings = next(backend.glob("*/settings.py")).read_text()
    assert ("api.security_headers.DjangoSecurityHeadersMiddleware" in settings) is enabled
    assert (backend / "api" / "security_headers.py").exists() is enabled


def test_asgi_middleware_keeps_headers_the_route_set():
    def framed(_):
        return PlainTextResponse("ok", headers={"x-frame-options": "SAMEORIGIN"})

    app = SecurityHeadersMiddleware(Starlette(routes=[Route("/", framed)]))
    headers = TestClient(app).get("/").headers
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["x-content-type-options"] == "nosniff"


def test_django_middleware_keeps_headers_the_view_set():
    response = SimpleNamespace(headers={"referrer-policy": "same-origin"})
    middleware = DjangoSecurityHeadersMiddleware(lambda request: response)
    assert middleware(object()).headers == {**dict(STANDARD_HEADERS), "referrer-policy": "same-origin"}
