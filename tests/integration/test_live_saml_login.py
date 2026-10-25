"""SAML login over real HTTP against `stackform run` and the generated FastAPI app, with a live signing IdP."""

import base64
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from tests.integration.support.apps import BACKENDS, Backend, launched
from tests.integration.support.saml import IdentityProvider, live_identity_provider

pytestmark = pytest.mark.integration

SPEC = Path(__file__).parents[1] / "fixtures" / "valid" / "auth-saml.yaml"
FRONTEND = "http://frontend.test"
EMAIL = "ada@example.com"
ORGANIZATION = "ACME"


@pytest.fixture(scope="module")
def identity_provider() -> Iterator[IdentityProvider]:
    attributes = {
        "urn:oid:0.9.2342.19200300.100.1.3": EMAIL,
        "displayName": "Ada Lovelace",
        "urn:oid:2.5.4.10": ORGANIZATION,
    }
    with live_identity_provider(EMAIL, attributes) as provider:
        yield provider


@contextmanager
def _serve(backend: Backend, spec: Path, workdir: Path, identity_provider: IdentityProvider) -> Iterator[str]:
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{workdir / 'saml.sqlite'}",
        "SAML_IDP_METADATA_URL": identity_provider.metadata_url,
        "JWT_SECRET": "saml-login-secret-of-sufficient-length",
        "FRONTEND_URL": FRONTEND,
    }
    with launched(backend, spec, workdir, env) as url:
        yield f"{url}/api/v1"


@pytest.fixture(scope="module", params=BACKENDS, ids=lambda backend: backend.name)
def api(request, tmp_path_factory, identity_provider) -> Iterator[str]:
    with _serve(request.param, SPEC, tmp_path_factory.mktemp(f"saml-{request.param.name}"), identity_provider) as url:
        yield url


@pytest.fixture(scope="module", params=BACKENDS, ids=lambda backend: backend.name)
def invitation_only_api(request, tmp_path_factory, identity_provider) -> Iterator[str]:
    workdir = tmp_path_factory.mktemp(f"saml-invitation-{request.param.name}")
    spec = workdir / "spec.yaml"
    spec.write_text(SPEC.read_text().replace("auto_provision: true", "auto_provision: false"))
    with _serve(request.param, spec, workdir, identity_provider) as url:
        yield url


@pytest.fixture
async def client(api):
    async with httpx.AsyncClient(base_url=api, timeout=30) as client:
        yield client


async def _identity_provider_post(client: httpx.AsyncClient, identity_provider: IdentityProvider) -> tuple[str, str]:
    """Start login at the SP and return the form the IdP has the browser post back: (action, SAMLResponse)."""
    login = await client.get("/users/auth/corporate")
    assert login.status_code in (302, 307)
    assert login.headers["location"].startswith(f"{identity_provider.sso_url}?SAMLRequest=")
    form = (await client.get(login.headers["location"])).text
    action, saml_response = re.search(r'action="([^"]+)".*value="([^"]+)"', form).groups()
    return unescape(action), saml_response


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signed_in(client: httpx.AsyncClient, identity_provider: IdentityProvider) -> str:
    """Complete a login and return the app token the login code exchanges for."""
    action, saml_response = await _identity_provider_post(client, identity_provider)
    callback = await client.post(action, data={"SAMLResponse": saml_response})
    assert callback.status_code == 303
    code = parse_qs(urlparse(callback.headers["location"]).query)["code"][0]
    return (await client.post("/auth/exchange", json={"code": code})).json()["token"]


async def _user(client: httpx.AsyncClient, token: str) -> dict:
    users = (await client.get("/users", headers=_bearer(token))).json()
    return next(user for user in users if user["email"] == EMAIL)


async def test_sign_in_resolves_relations_and_exchanges_the_login_code(client, identity_provider):
    organization = await client.post("/organizations", json={"name": "Acme Corporation", "code": ORGANIZATION})
    assert organization.status_code in (200, 201)

    action, saml_response = await _identity_provider_post(client, identity_provider)
    callback = await client.post(action, data={"SAMLResponse": saml_response})
    assert callback.status_code == 303
    location = urlparse(callback.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{FRONTEND}/auth/callback"

    exchange = await client.post("/auth/exchange", json={"code": parse_qs(location.query)["code"][0]})
    assert exchange.status_code == 200
    users = await client.get("/users", headers={"Authorization": f"Bearer {exchange.json()['token']}"})

    assert users.status_code == 200
    (user,) = users.json()
    assert (user["email"], user["name"], user["organizationId"]) == (
        EMAIL,
        "Ada Lovelace",
        organization.json()["id"],
    )


async def test_login_code_is_single_use(client, identity_provider):
    action, saml_response = await _identity_provider_post(client, identity_provider)
    callback = await client.post(action, data={"SAMLResponse": saml_response})
    code = parse_qs(urlparse(callback.headers["location"]).query)["code"][0]

    assert (await client.post("/auth/exchange", json={"code": code})).status_code == 200
    assert (await client.post("/auth/exchange", json={"code": code})).status_code == 401


async def test_tampered_assertion_is_rejected(client, identity_provider):
    action, saml_response = await _identity_provider_post(client, identity_provider)
    forged = base64.b64decode(saml_response).replace(EMAIL.encode(), b"mallory@example.com")

    callback = await client.post(action, data={"SAMLResponse": base64.b64encode(forged).decode()})

    assert callback.status_code == 401


async def test_callback_without_response_is_a_bad_request(client):
    assert (await client.post("/users/auth/corporate/callback", data={})).status_code == 400


async def test_metadata_publishes_the_service_provider(client, api):
    metadata = await client.get("/users/auth/corporate/metadata")

    assert metadata.status_code == 200
    assert metadata.headers["content-type"].startswith("application/xml")
    assert 'entityID="https://sp.example.com/metadata"' in metadata.text
    assert f'Location="{api}/users/auth/corporate/callback"' in metadata.text


async def test_logout_without_single_logout_service_is_not_implemented(client):
    assert (await client.get("/users/auth/corporate/logout")).status_code == 501


async def test_unknown_user_is_refused_without_auto_provision(invitation_only_api, identity_provider):
    async with httpx.AsyncClient(base_url=invitation_only_api, timeout=30) as client:
        action, saml_response = await _identity_provider_post(client, identity_provider)
        callback = await client.post(action, data={"SAMLResponse": saml_response})

    assert callback.status_code == 403


async def test_signing_in_again_keeps_the_user_and_refreshes_mapped_fields(client, identity_provider):
    first_token = await _signed_in(client, identity_provider)
    before = await _user(client, first_token)
    with identity_provider.asserting({"displayName": "Ada King"}):
        after = await _user(client, await _signed_in(client, identity_provider))

    assert (after["id"], after["name"]) == (before["id"], "Ada King")
    assert (await client.get("/users", headers=_bearer(first_token))).status_code == 200


async def test_multi_valued_claim_leaves_the_relation_unset(client, identity_provider):
    with identity_provider.asserting({"urn:oid:2.5.4.10": [ORGANIZATION, "BETA"]}):
        token = await _signed_in(client, identity_provider)

    assert (await _user(client, token))["organizationId"] is None


async def test_string_claim_matches_a_number_field(client, identity_provider):
    organization = await client.post("/organizations", json={"name": "Registered", "code": "REG", "registry": 42})
    with identity_provider.asserting({"registryNumber": "42"}):
        token = await _signed_in(client, identity_provider)

    assert (await _user(client, token))["registeredOrganizationId"] == organization.json()["id"]


@pytest.mark.parametrize(
    "saml_response", ["not-base64!!", base64.b64encode(b"<unclosed").decode()], ids=["base64", "xml"]
)
async def test_malformed_response_is_a_bad_request(client, saml_response):
    callback = await client.post("/users/auth/corporate/callback", data={"SAMLResponse": saml_response})

    assert callback.status_code == 400


async def test_replayed_assertion_is_rejected(client, identity_provider):
    action, saml_response = await _identity_provider_post(client, identity_provider)

    assert (await client.post(action, data={"SAMLResponse": saml_response})).status_code == 303
    assert (await client.post(action, data={"SAMLResponse": saml_response})).status_code == 401


async def test_identity_record_is_created_without_provider_fields(client, identity_provider):
    token = await _signed_in(client, identity_provider)

    created = await client.post(
        "/users", json={"email": "grace@example.com", "name": "Grace Hopper"}, headers=_bearer(token)
    )

    assert created.is_success
    assert created.json()["email"] == "grace@example.com"
