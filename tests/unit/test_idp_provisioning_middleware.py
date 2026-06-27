"""Integration-style tests for IdP provisioning middleware.

Verifies that the first authenticated request to a route that does NOT inject
the principal (e.g. GET /users/{id}) still triggers verification+provisioning
so the user row (id==sub) exists before the route handler executes.
"""

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from yaml_api_generator.ir import IRProviderBinding
from yaml_api_generator.ir.api import IROIDCProvider
from yaml_api_generator.server.common.auth import idp
from yaml_api_generator.server.common.server_context import (
    RuntimeAppConfig,
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeContext,
    RuntimeIdentityDescriptor,
    RuntimeRouteDescriptor,
)
from yaml_api_generator.server.common.repositories import BaseRepository, RepositoryRegistry
from yaml_api_generator.server.fastapi.factory import register_fastapi_routes
from yaml_api_generator.server.fastapi.server import _idp_provisioning_middleware

_ISSUER = "https://kc.test/realms/test"
_CLIENT_ID = "test-app"
_JWKS_URI = "https://kc.test/jwks"
_DISCOVERY_URL = "https://kc.test/.well-known/openid-configuration"


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _patch_jwks(rsa_key, monkeypatch):
    async def fake_discovery(_url):
        return {"jwks_uri": _JWKS_URI, "issuer": _ISSUER}

    async def fake_get_signing_key(_jwks_uri: str, _kid: str):
        class _Key:
            key = rsa_key.public_key()
        return _Key()

    monkeypatch.setattr(idp, "_discovery", fake_discovery)
    monkeypatch.setattr(idp, "_get_signing_key", fake_get_signing_key)


class _FakeRepo(BaseRepository):
    def __init__(self):
        self.docs: list[dict] = []
        self._id_fields: dict[str, str] = {}

    def register_id_field(self, collection: str, id_field: str) -> None:
        self._id_fields[collection] = id_field

    def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def list(self, _collection: str) -> list[dict]:
        return list(self.docs)

    async def get(self, collection: str, document_id: str) -> dict | None:
        id_field = self._id_fields.get(collection, "id")
        return next((d for d in self.docs if str(d.get(id_field, "")) == document_id), None)

    async def create(self, _collection: str, payload: dict) -> dict:
        self.docs.append(payload)
        return payload

    async def update(self, _collection: str, document_id: str, payload: dict) -> dict | None:
        return None

    async def replace(self, _collection: str, document_id: str, payload: dict) -> dict | None:
        return None

    async def delete(self, _collection: str, document_id: str) -> dict | None:
        return None


def _sign(rsa_key: Any, **claims: Any) -> str:
    payload = {"iss": _ISSUER, "aud": _CLIENT_ID, "exp": int(time.time()) + 300, **claims}
    return jwt.encode(payload, rsa_key, algorithm="RS256")


def _build_ctx(identity: RuntimeIdentityDescriptor) -> RuntimeContext:
    provider = IROIDCProvider(
        name="keycloak",
        client_id=_CLIENT_ID,
        trust="idp",
        discovery_url=_DISCOVERY_URL,
        issuer=_ISSUER,
        audiences=(_CLIENT_ID,),
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
    routes = [
        RuntimeRouteDescriptor(
            method="GET",
            path="/users/{id}",
            operation="get",
            collection="users",
            is_public=True,
        ),
    ]
    return RuntimeContext(
        app=RuntimeAppConfig(base_path="", api_version=None),
        collections={"users": collection},
        routes=routes,
        auth=auth,
    )


def _build_identity(auto_provision: bool = True) -> RuntimeIdentityDescriptor:
    return RuntimeIdentityDescriptor(
        name="users",
        bindings=(IRProviderBinding(
            provider="keycloak",
            identifier="email",
            claim_mapping={"email": "email"},
            auto_provision=auto_provision,
        ),),
        id_field="id",
    )


def _build_app(repo: _FakeRepo, identity: RuntimeIdentityDescriptor):
    from fastapi import FastAPI
    ctx = _build_ctx(identity)
    registry = RepositoryRegistry(
        repositories={"mongo": repo},
        bindings={"users": "mongo"},
        default="mongo",
    )
    registry.for_collection("users").register_id_field("users", "id")

    app = FastAPI()
    app.add_middleware(_idp_provisioning_middleware(ctx, registry))
    register_fastapi_routes(app, ctx, registry)
    return app


def test_get_by_id_with_idp_token_provisions_user_first(rsa_key):
    """GET /users/{sub} with a valid IdP token provisions the user row before handler."""
    repo = _FakeRepo()
    sub = "kc-test-sub"
    token = _sign(rsa_key, sub=sub, email="alice@test.com")

    app = _build_app(repo, _build_identity(auto_provision=True))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/users/{sub}", headers={"Authorization": f"Bearer {token}"})

    assert len(repo.docs) == 1, "User row must be provisioned by the middleware"
    assert repo.docs[0]["id"] == sub
    assert response.status_code not in (404, 500)


def test_get_by_id_service_token_does_not_provision_user(rsa_key):
    """Service-account tokens (no identifier claim) must NOT create a user row."""
    repo = _FakeRepo()
    sub = "svc-client"
    payload = {"iss": _ISSUER, "aud": _CLIENT_ID, "exp": int(time.time()) + 300, "sub": sub, "azp": "my-service"}
    token = jwt.encode(payload, rsa_key, algorithm="RS256")

    app = _build_app(repo, _build_identity(auto_provision=True))
    with TestClient(app, raise_server_exceptions=False) as client:
        client.get(f"/users/{sub}", headers={"Authorization": f"Bearer {token}"})

    assert len(repo.docs) == 0, "Service-account token must not provision a user row"


def test_get_by_id_auto_provision_disabled_unknown_sub_returns_401(rsa_key):
    """auto_provision=false + unknown sub must be rejected with 401."""
    repo = _FakeRepo()
    token = _sign(rsa_key, sub="kc-unknown", email="unknown@test.com")

    app = _build_app(repo, _build_identity(auto_provision=False))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/users/kc-unknown", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert len(repo.docs) == 0
