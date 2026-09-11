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
_CLIENT_ID = "my-app"
_JWKS_URI = "https://kc.test/jwks"
_DISCOVERY_URL = "https://kc.test/.well-known/openid-configuration"


class _FakeRepo:
    def __init__(self):
        self.docs: list[dict] = []

    async def list(self, _collection):
        return list(self.docs)

    async def create(self, _collection, payload):
        self.docs.append(payload)
        return payload

    async def update(self, _collection, document_id, payload):
        for doc in self.docs:
            if str(doc.get("id", "")) == str(document_id):
                doc.update(payload)
                return doc
        return None

    async def upsert_by(self, _collection, key_field, payload):
        for doc in self.docs:
            if str(doc.get(key_field)) == str(payload.get(key_field)):
                doc.update(payload)
                return doc
        self.docs.append(payload)
        return payload


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


def _provider_with_overrides() -> IROIDCProvider:
    return IROIDCProvider(
        name="keycloak",
        client_id=_CLIENT_ID,
        trust="idp",
        discovery_url=_DISCOVERY_URL,
        issuer=_ISSUER,
        audiences=(_AUDIENCE,),
    )


def _provider_minimal() -> IROIDCProvider:
    """Provider with only discovery_url + client_id; no issuer/audience override."""
    return IROIDCProvider(
        name="keycloak",
        client_id=_CLIENT_ID,
        trust="idp",
        discovery_url=_DISCOVERY_URL,
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
    payload = {"iss": _ISSUER, "aud": _CLIENT_ID, "exp": int(time.time()) + 300, **claims}
    return jwt.encode(payload, rsa_key, algorithm="RS256")


_COLLECTION = RuntimeCollectionDescriptor(
    name="users", type="auth", id_field="id", id_format="uuidv7", fields={}
)
_COLLECTIONS = {"users": _COLLECTION}


async def test_valid_idp_token_provisions_and_resolves_principal(rsa_key):
    repo = _FakeRepo()
    token = _sign(rsa_key, sub="kc-123", email="alice@example.com")

    principal = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": _provider_with_overrides()}, _registry(repo),
    )

    assert principal is not None
    assert principal["identity_collection"] == "users"
    assert principal["record"]["email"] == "alice@example.com"
    assert len(repo.docs) == 1


async def test_idp_provision_sets_primary_id_to_sub(rsa_key):
    repo = _FakeRepo()
    token = _sign(rsa_key, sub="kc-abc-123", email="bob@example.com")

    principal = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": _provider_with_overrides()}, _registry(repo),
    )

    assert principal is not None
    assert principal["sub"] == "kc-abc-123"
    assert repo.docs[0]["id"] == "kc-abc-123"
    assert repo.docs[0]["email"] == "bob@example.com"


async def test_second_idp_login_with_same_sub_returns_same_record(rsa_key):
    repo = _FakeRepo()
    token = _sign(rsa_key, sub="kc-xyz", email="carol@example.com")

    first = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": _provider_with_overrides()}, _registry(repo),
    )
    second = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": _provider_with_overrides()}, _registry(repo),
    )

    assert first is not None and second is not None
    assert first["sub"] == second["sub"] == "kc-xyz"
    assert len(repo.docs) == 1


async def test_idp_auto_provision_disabled_rejects_unknown_sub(rsa_key):
    from yaml_api_generator.server.common.steps.authorization import UnauthorizedError

    identity = RuntimeIdentityDescriptor(
        name="users",
        bindings=(IRProviderBinding(
            provider="keycloak", identifier="email",
            claim_mapping={"email": "email"}, auto_provision=False,
        ),),
        id_field="id",
    )
    repo = _FakeRepo()
    token = _sign(rsa_key, sub="kc-new", email="dave@example.com")

    with pytest.raises(UnauthorizedError):
        await _resolve_idp_principal(
            token, {"users": identity}, _COLLECTIONS,
            {"keycloak": _provider_with_overrides()}, _registry(repo),
        )

    assert len(repo.docs) == 0


async def test_issuer_derived_from_discovery_when_not_in_spec(rsa_key):
    """Without issuer in spec, the provider must derive it from the discovery doc."""
    repo = _FakeRepo()
    token = _sign(rsa_key, sub="kc-123", email="alice@example.com")

    principal = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": _provider_minimal()}, _registry(repo),
    )

    assert principal is not None
    assert principal["record"]["email"] == "alice@example.com"


async def test_audience_defaults_to_client_id(rsa_key):
    """When no audience is declared, the token aud is verified against client_id."""
    token = _sign(rsa_key, sub="kc-123", email="b@example.com", aud=_CLIENT_ID)
    repo = _FakeRepo()

    principal = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": _provider_minimal()}, _registry(repo),
    )
    assert principal is not None


async def test_audience_override_is_honored(rsa_key):
    """An explicit audiences list is used instead of client_id."""
    override_audience = "api://my-api"
    provider = IROIDCProvider(
        name="keycloak",
        client_id=_CLIENT_ID,
        trust="idp",
        discovery_url=_DISCOVERY_URL,
        audiences=(override_audience,),
    )
    payload = {"iss": _ISSUER, "aud": override_audience, "exp": int(time.time()) + 300, "sub": "x", "email": "c@example.com"}
    token = jwt.encode(payload, rsa_key, algorithm="RS256")
    repo = _FakeRepo()

    principal = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": provider}, _registry(repo),
    )
    assert principal is not None


async def test_token_from_unknown_issuer_is_not_an_idp_token(rsa_key):
    token = _sign(rsa_key, sub="x", email="a@b.com", iss="https://other/realms/x")
    result = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": _provider_with_overrides()}, _registry(_FakeRepo()),
    )
    assert result is None


async def test_wrong_audience_is_rejected(rsa_key):
    from yaml_api_generator.server.common.steps.authorization import UnauthorizedError

    token = _sign(rsa_key, sub="x", email="a@b.com", aud="someone-else")
    with pytest.raises(UnauthorizedError):
        await _resolve_idp_principal(
            token, {"users": _identity()}, _COLLECTIONS,
            {"keycloak": _provider_with_overrides()}, _registry(_FakeRepo()),
        )


async def test_default_audience_rejects_wrong_aud(rsa_key):
    """Without an audience override, aud != client_id must be rejected."""
    from yaml_api_generator.server.common.steps.authorization import UnauthorizedError

    payload = {"iss": _ISSUER, "aud": "some-other-client", "exp": int(time.time()) + 300, "sub": "x", "email": "a@b.com"}
    token = jwt.encode(payload, rsa_key, algorithm="RS256")
    with pytest.raises(UnauthorizedError):
        await _resolve_idp_principal(
            token, {"users": _identity()}, _COLLECTIONS,
            {"keycloak": _provider_minimal()}, _registry(_FakeRepo()),
        )


async def test_audience_override_rejects_wrong_aud(rsa_key):
    """An explicit audiences list must reject tokens whose aud does not match."""
    from yaml_api_generator.server.common.steps.authorization import UnauthorizedError

    override_audience = "api://my-api"
    provider = IROIDCProvider(
        name="keycloak",
        client_id=_CLIENT_ID,
        trust="idp",
        discovery_url=_DISCOVERY_URL,
        audiences=(override_audience,),
    )
    payload = {"iss": _ISSUER, "aud": _CLIENT_ID, "exp": int(time.time()) + 300, "sub": "x", "email": "a@b.com"}
    token = jwt.encode(payload, rsa_key, algorithm="RS256")
    with pytest.raises(UnauthorizedError):
        await _resolve_idp_principal(
            token, {"users": _identity()}, _COLLECTIONS,
            {"keycloak": provider}, _registry(_FakeRepo()),
        )


async def test_multiple_audiences_accepted(rsa_key):
    """Any audience in the accepted set should pass verification."""
    provider = IROIDCProvider(
        name="keycloak",
        client_id=_CLIENT_ID,
        trust="idp",
        discovery_url=_DISCOVERY_URL,
        audiences=("api://resource", _AUDIENCE),
    )
    token = _sign(rsa_key, sub="kc-multi", email="multi@example.com", aud=_AUDIENCE)
    repo = _FakeRepo()

    principal = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": provider}, _registry(repo),
    )
    assert principal is not None


async def test_service_principal_returned_when_identifier_claim_absent(rsa_key):
    """M2M token without email yields a service principal — no user row created."""
    repo = _FakeRepo()
    payload = {
        "iss": _ISSUER,
        "aud": _CLIENT_ID,
        "exp": int(time.time()) + 300,
        "sub": "svc-client-id",
        "azp": "my-service",
    }
    token = jwt.encode(payload, rsa_key, algorithm="RS256")

    principal = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": _provider_with_overrides()}, _registry(repo),
    )

    assert principal is not None
    assert principal["is_service"] is True
    assert principal["sub"] == "svc-client-id"
    assert principal["client_id"] == "my-service"
    assert principal["record"] is None
    assert principal["identity_collection"] is None
    assert len(repo.docs) == 0


async def test_service_principal_with_email_creates_user(rsa_key):
    """A token WITH email always yields a user principal (lookup-or-create)."""
    repo = _FakeRepo()
    token = _sign(rsa_key, sub="kc-user", email="user@example.com")

    principal = await _resolve_idp_principal(
        token, {"users": _identity()}, _COLLECTIONS,
        {"keycloak": _provider_with_overrides()}, _registry(repo),
    )

    assert principal is not None
    assert principal.get("is_service") is not True
    assert principal["record"] is not None
    assert len(repo.docs) == 1
