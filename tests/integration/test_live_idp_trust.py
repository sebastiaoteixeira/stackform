"""IdP bearer tokens over real HTTP against `stackform run` and the generated FastAPI app, on a SQL datastore."""

import os
from collections.abc import Iterator

import httpx
import pytest

from tests.integration.support.apps import BACKENDS, launched
from tests.integration.support.oidc import Issuer, live_issuer

pytestmark = pytest.mark.integration

AUDIENCE = "my-app"
CONFIGURED_ISSUER = "https://configured-issuer.example"

SPEC = """
version: "0.2"
api:
  basePath: /api
  version: v1
providers:
  corp:
    type: oidc
    trust: idp
    client_id: my-app
    discovery_url: "${CORP_DISCOVERY_URL}"
    issuer: "${CORP_ISSUER}"
    audiences: [my-app]
datastores:
  default:
    type: postgres
    dsn: ${DATABASE_URL}
entities:
  user:
    type: auth
    auth:
      via:
        - provider: corp
          identifier: email
          claim_mapping:
            email: email
            name: name
          auto_provision: true
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      name: { type: string }
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
def issuer() -> Iterator[Issuer]:
    with live_issuer(AUDIENCE) as issuer:
        yield issuer


@pytest.fixture(scope="module", params=BACKENDS, ids=lambda backend: backend.name)
def api(request, tmp_path_factory, issuer) -> Iterator[str]:
    workdir = tmp_path_factory.mktemp(f"idp-{request.param.name}")
    spec = workdir / "spec.yaml"
    spec.write_text(SPEC)
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{workdir / 'idp.sqlite'}",
        "CORP_DISCOVERY_URL": issuer.discovery_url,
        "CORP_ISSUER": CONFIGURED_ISSUER,
        "JWT_SECRET": "idp-trust-secret-of-sufficient-length",
    }
    with launched(request.param, spec, workdir, env) as url:
        yield f"{url}/api/v1"


@pytest.fixture
async def client(api):
    async with httpx.AsyncClient(base_url=api, timeout=30) as client:
        yield client


async def test_token_from_the_configured_issuer_signs_the_user_in(client, issuer):
    headers = issuer.bearer("ada", iss=CONFIGURED_ISSUER, email="ada@example.com", name="Ada")

    users = await client.get("/users", headers=headers)

    assert users.status_code == 200
    assert [(user["id"], user["email"]) for user in users.json()] == [("ada", "ada@example.com")]


async def test_token_from_the_discovered_issuer_is_untrusted_when_another_is_configured(client, issuer):
    users = await client.get("/users", headers=issuer.bearer("eve", email="eve@example.com"))

    assert users.status_code == 401


async def test_signing_in_again_keeps_the_user_and_refreshes_mapped_fields(client, issuer):
    first = issuer.bearer("grace", iss=CONFIGURED_ISSUER, email="grace@example.com", name="Grace")
    second = issuer.bearer("grace", iss=CONFIGURED_ISSUER, email="grace@example.com", name="Grace Hopper")

    assert (await client.get("/users", headers=first)).status_code == 200
    users = (await client.get("/users", headers=second)).json()

    assert [user["name"] for user in users if user["id"] == "grace"] == ["Grace Hopper"]
