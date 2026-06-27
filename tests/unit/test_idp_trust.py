import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from yaml_api_generator.ir import IRProviderBinding
from yaml_api_generator.ir.api import IROIDCProvider
from yaml_api_generator.server.common.auth import idp
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.common.server_context import (
    RuntimeCollectionDescriptor,
    RuntimeIdentityDescriptor,
)
from yaml_api_generator.server.common.steps.authentication import _resolve_idp_principal

_ISSUER = "https://kc.test/realms/main"
_AUDIENCE = "my-app"
_JWKS_URI = "https://kc.test/jwks"


class _FakeRepo:
    def __init__(self):
        self.docs: list[dict] = []

    async def list(self, _collection):
        return list(self.docs)

    async def create(self, _collection, payload):
        self.docs.append(payload)
        return payload


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKClient:
    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token):
        return _FakeSigningKey(self._public_key)


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _patch_jwks(rsa_key, monkeypatch):
    async def fake_discovery(_url):
        return {"jwks_uri": _JWKS_URI}

    monkeypatch.setattr(idp, "_discovery", fake_discovery)
    idp._jwks_clients[_JWKS_URI] = _FakeJWKClient(rsa_key.public_key())
    yield
    idp._jwks_clients.pop(_JWKS_URI, None)


def _provider() -> IROIDCProvider:
    return IROIDCProvider(
        name="keycloak", client_id="cid", trust="idp",
        issuer=_ISSUER, audience=_AUDIENCE,
    )


def _identity() -> RuntimeIdentityDescriptor:
    return RuntimeIdentityDescriptor(
        name="users",
        bindings=(IRProviderBinding(
            provider="keycloak", identifier="email",
            claim_mapping={"email": "email"}, auto_provision=True,
        ),),
        id_field="id",
    )


def _registry(repo) -> RepositoryRegistry:
    return RepositoryRegistry(repositories={"mongo": repo}, bindings={}, default="mongo")


def _sign(rsa_key, **claims) -> str:
    payload = {"iss": _ISSUER, "aud": _AUDIENCE, "exp": int(time.time()) + 300, **claims}
    return jwt.encode(payload, rsa_key, algorithm="RS256")


async def test_valid_idp_token_provisions_and_resolves_principal(rsa_key):
    repo = _FakeRepo()
    token = _sign(rsa_key, sub="kc-123", email="alice@example.com")

    principal = await _resolve_idp_principal(
        token, {"users": _identity()},
        {"users": RuntimeCollectionDescriptor(name="users", type="auth", id_field="id", id_format="uuidv7", fields={})},
        {"keycloak": _provider()}, _registry(repo),
    )

    assert principal is not None
    assert principal["identity_collection"] == "users"
    assert principal["record"]["email"] == "alice@example.com"
    assert len(repo.docs) == 1


async def test_token_from_unknown_issuer_is_not_an_idp_token(rsa_key):
    token = _sign(rsa_key, sub="x", email="a@b.com", iss="https://other/realms/x")
    result = await _resolve_idp_principal(
        token, {"users": _identity()},
        {"users": RuntimeCollectionDescriptor(name="users", type="auth", id_field="id", id_format="uuidv7", fields={})},
        {"keycloak": _provider()}, _registry(_FakeRepo()),
    )
    assert result is None


async def test_wrong_audience_is_rejected(rsa_key):
    from yaml_api_generator.server.common.steps.authorization import UnauthorizedError

    token = _sign(rsa_key, sub="x", email="a@b.com", aud="someone-else")
    with pytest.raises(UnauthorizedError):
        await _resolve_idp_principal(
            token, {"users": _identity()},
            {"users": RuntimeCollectionDescriptor(name="users", type="auth", id_field="id", id_format="uuidv7", fields={})},
            {"keycloak": _provider()}, _registry(_FakeRepo()),
        )
