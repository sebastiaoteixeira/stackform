from fastapi import FastAPI
from fastapi.testclient import TestClient

from yaml_api_generator.ir import IRProviderBinding
from yaml_api_generator.ir.api import IROIDCProvider
from yaml_api_generator.server.common.auth import oidc
from yaml_api_generator.server.common.auth.login_codes import LoginCodeStore
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.common.server_context import (
    RuntimeAppConfig,
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeContext,
    RuntimeIdentityDescriptor,
)
from yaml_api_generator.server.fastapi.factory import register_provider_routes


_DISCOVERY_URL = "https://idp.test/.well-known/openid-configuration"


def _ctx() -> RuntimeContext:
    provider = IROIDCProvider(
        name="keycloak",
        client_id="cid",
        client_secret="csecret",
        discovery_url=_DISCOVERY_URL,
    )
    identity = RuntimeIdentityDescriptor(
        name="users",
        bindings=(IRProviderBinding(provider="keycloak", identifier="email"),),
        id_field="id",
    )
    collection = RuntimeCollectionDescriptor(
        name="users", type="auth", id_field="id", id_format="uuidv7", fields={}
    )
    auth = RuntimeAuthConfig(
        enabled=True,
        identity_collections={"users": identity},
        identity_id_fields={"users": "id"},
        has_password_auth=False,
        has_api_key_auth=False,
        providers={"keycloak": provider},
    )
    return RuntimeContext(
        app=RuntimeAppConfig(base_path="/api", api_version="v1"),
        collections={"users": collection},
        routes=[],
        auth=auth,
        operations={},
    )


def _client() -> TestClient:
    app = FastAPI()
    register_provider_routes(app, _ctx(), RepositoryRegistry(repositories={}, bindings={}, default=""))
    return TestClient(app)


def test_providers_listing_route_is_mounted():
    resp = _client().get("/api/v1/users/auth/providers")
    assert resp.status_code == 200
    assert resp.json() == [{"name": "keycloak", "type": "oidc"}]


def test_login_route_redirects_to_idp():
    oidc._discovery_cache[_DISCOVERY_URL] = {
        "authorization_endpoint": "https://idp.test/authorize",
        "token_endpoint": "https://idp.test/token",
        "userinfo_endpoint": "https://idp.test/userinfo",
    }
    resp = _client().get("/api/v1/users/auth/keycloak", follow_redirects=False)
    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert location.startswith("https://idp.test/authorize?")
    assert "client_id=cid" in location
    assert "response_type=code" in location


def test_logout_route_redirects_to_end_session():
    oidc._discovery_cache[_DISCOVERY_URL] = {
        "authorization_endpoint": "https://idp.test/authorize",
        "token_endpoint": "https://idp.test/token",
        "userinfo_endpoint": "https://idp.test/userinfo",
        "end_session_endpoint": "https://idp.test/logout",
    }
    resp = _client().get("/api/v1/users/auth/keycloak/logout", follow_redirects=False)
    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert location.startswith("https://idp.test/logout?")
    assert "client_id=cid" in location
    assert "post_logout_redirect_uri=" in location


def test_exchange_route_rejects_bad_code():
    resp = _client().post("/api/v1/auth/exchange", json={"code": "nope"})
    assert resp.status_code == 401


def test_exchange_route_requires_code():
    resp = _client().post("/api/v1/auth/exchange", json={})
    assert resp.status_code == 400


def test_login_codes_single_use_and_resolve():
    store = LoginCodeStore()
    code = store.issue("user-1", "users")
    assert store.redeem(code) == ("user-1", "users")
    assert store.redeem(code) is None
