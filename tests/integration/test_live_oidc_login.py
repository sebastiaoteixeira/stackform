"""OIDC app login over real HTTP against `stackform run` and the generated FastAPI app, with a confidential client."""

import os
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from tests.integration.support.apps import BACKENDS, launched
from tests.integration.support.oidc import AuthorizationServer, live_authorization_server

pytestmark = pytest.mark.integration

FRONTEND = "http://frontend.test"
CLIENT_SECRET = "secret-written-in-the-spec"
USERINFO = {"sub": "grace", "email": "grace@example.com", "name": "Grace Hopper"}

SPEC = f"""
version: "0.2"
api:
  basePath: /api
  version: v1
providers:
  corp-sso:
    type: oidc
    client_id: my-app
    client_secret: {CLIENT_SECRET}
    discovery_url: "${{CORP_SSO_DISCOVERY_URL}}"
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
        - provider: corp-sso
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


@pytest.fixture(scope="module", params=BACKENDS, ids=lambda backend: backend.name)
def api(request, tmp_path_factory, authorization_server) -> Iterator[str]:
    workdir = tmp_path_factory.mktemp(f"oidc-{request.param.name}")
    spec = workdir / "spec.yaml"
    spec.write_text(SPEC)
    env = {
        **{name: value for name, value in os.environ.items() if not name.endswith("_CLIENT_SECRET")},
        "DATABASE_URL": f"sqlite+aiosqlite:///{workdir / 'oidc.sqlite'}",
        "CORP_SSO_DISCOVERY_URL": authorization_server.discovery_url,
        "JWT_SECRET": "oidc-login-secret-of-sufficient-length",
        "FRONTEND_URL": FRONTEND,
    }
    with launched(request.param, spec, workdir, env) as url:
        yield f"{url}/api/v1"


async def test_client_secret_from_the_spec_signs_the_user_in(api):
    async with httpx.AsyncClient(base_url=api, timeout=30) as client:
        login = await client.get("/users/auth/corp-sso")
        assert login.status_code in (302, 307)
        authorization = await client.get(login.headers["location"])
        callback = await client.get(authorization.headers["location"])
        assert callback.status_code == 303
        location = urlparse(callback.headers["location"])
        assert f"{location.scheme}://{location.netloc}{location.path}" == f"{FRONTEND}/auth/callback"

        exchange = await client.post("/auth/exchange", json={"code": parse_qs(location.query)["code"][0]})
        users = await client.get("/users", headers={"Authorization": f"Bearer {exchange.json()['token']}"})

    assert users.status_code == 200
    (user,) = users.json()
    assert (user["email"], user["name"]) == (USERINFO["email"], USERINFO["name"])
