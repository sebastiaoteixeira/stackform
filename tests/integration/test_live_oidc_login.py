"""OIDC app login over real HTTP against `stackform run` and the generated FastAPI app, with a confidential client."""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from tests.integration.support.apps import BACKENDS, launched
from tests.integration.support.oidc import AuthorizationServer, live_authorization_server

pytestmark = pytest.mark.integration

FRONTEND = "http://frontend.test"
CLIENT_SECRET = "secret-written-in-the-spec"
USERINFO = {"sub": "grace", "email": "grace@example.com", "name": "Grace Hopper"}
# "github" is an ordinary OIDC provider name: its endpoints come from discovery like any other
PROVIDERS = ("corp-sso", "github")

SPEC = """
version: "0.2"
api:
  basePath: /api
  version: v1
providers:
  {provider}:
    type: oidc
    client_id: my-app
    client_secret: {client_secret}
    discovery_url: "${{DISCOVERY_URL}}"
datastores:
  default:
    type: postgres
    dsn: ${{DATABASE_URL}}
entities:
  user:
    type: auth
    auth:
      identifier: email
      via:
        - provider: {provider}
          claim_mapping:
            email: email
            name: name
          auto_provision: true
    fields:
      id: {{ type: id }}
      email: {{ type: string, required: true, unique: true }}
      name: {{ type: string, required: true }}
repositories:
  users:
    entity: user
services:
  users:
    repository: users
controllers:
  users:
    service: users
    base_path: /users
    access: "*"
"""


@pytest.fixture(scope="module")
def authorization_server() -> Iterator[AuthorizationServer]:
    with live_authorization_server(CLIENT_SECRET, USERINFO) as server:
        yield server


@dataclass(frozen=True)
class App:
    url: str
    provider: str


@pytest.fixture(
    scope="module",
    params=[(backend, provider) for backend in BACKENDS for provider in PROVIDERS],
    ids=lambda param: f"{param[0].name}-{param[1]}",
)
def app(request, tmp_path_factory, authorization_server) -> Iterator[App]:
    backend, provider = request.param
    workdir = tmp_path_factory.mktemp(f"oidc-{backend.name}-{provider}")
    spec = workdir / "spec.yaml"
    spec.write_text(SPEC.format(provider=provider, client_secret=CLIENT_SECRET))
    env = {
        **{name: value for name, value in os.environ.items() if not name.endswith("_CLIENT_SECRET")},
        "DATABASE_URL": f"sqlite+aiosqlite:///{workdir / 'oidc.sqlite'}",
        "DISCOVERY_URL": authorization_server.discovery_url,
        "JWT_SECRET": "oidc-login-secret-of-sufficient-length",
        "FRONTEND_URL": FRONTEND,
    }
    with launched(backend, spec, workdir, env) as url:
        yield App(f"{url}/api/v1", provider)


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(base_url=app.url, timeout=30) as client:
        yield client


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signed_in(client: httpx.AsyncClient, provider: str) -> str:
    """Complete a login and return the app token the login code exchanges for."""
    login = await client.get(f"/users/auth/{provider}")
    assert login.status_code in (302, 307)
    authorization = await client.get(login.headers["location"])
    callback = await client.get(authorization.headers["location"])
    assert callback.status_code == 303
    location = urlparse(callback.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{FRONTEND}/auth/callback"
    exchange = await client.post("/auth/exchange", json={"code": parse_qs(location.query)["code"][0]})
    return exchange.json()["token"]


async def test_client_secret_from_the_spec_signs_the_user_in(client, app):
    users = await client.get("/users", headers=_bearer(await _signed_in(client, app.provider)))

    assert users.status_code == 200
    (user,) = users.json()
    assert (user["email"], user["name"]) == (USERINFO["email"], USERINFO["name"])


async def test_signing_in_again_keeps_the_user_and_refreshes_mapped_fields(client, app, authorization_server):
    first_token = await _signed_in(client, app.provider)
    (before,) = (await client.get("/users", headers=_bearer(first_token))).json()
    with authorization_server.asserting({"name": "Grace Brewster Hopper"}):
        second_token = await _signed_in(client, app.provider)
    (after,) = (await client.get("/users", headers=_bearer(second_token))).json()

    assert (after["id"], after["name"]) == (before["id"], "Grace Brewster Hopper")
    assert (await client.get("/users", headers=_bearer(first_token))).status_code == 200
