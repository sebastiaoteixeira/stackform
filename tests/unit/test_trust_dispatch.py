"""Strict iss-based dispatch in the dev-server principal resolution.

A bearer JWT is verified against a single verifier chosen by its ``iss`` claim:
a trusted IdP issuer is verified against that IdP, a token whose issuer matches
no trusted IdP is rejected outright, and a bearer with no issuer (an app token
or an opaque api key) falls through to the app-token / credential paths.
"""

import time

import jwt
import pytest

from yaml_api_generator.ir import IRProviderBinding
from yaml_api_generator.ir.api import IROIDCProvider
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.common.server_context import (
    RuntimeCollectionDescriptor,
    RuntimeIdentityDescriptor,
)
from yaml_api_generator.server.common.steps.authentication import (
    _has_idp_provider,
    _resolve_identity_principal,
)
from yaml_api_generator.server.common.steps.authorization import UnauthorizedError

_ISSUER = "https://kc.test/realms/main"
_CLIENT_ID = "my-app"
_DISCOVERY_URL = "https://kc.test/.well-known/openid-configuration"


class _FakeRepo:
    async def list(self, _collection):
        return []


def _registry() -> RepositoryRegistry:
    return RepositoryRegistry(repositories={"mongo": _FakeRepo()}, bindings={}, default="mongo")


def _idp_provider() -> IROIDCProvider:
    return IROIDCProvider(
        name="keycloak",
        client_id=_CLIENT_ID,
        trust="idp",
        discovery_url=_DISCOVERY_URL,
        issuer=_ISSUER,
        audiences=(_CLIENT_ID,),
    )


def _identity() -> RuntimeIdentityDescriptor:
    return RuntimeIdentityDescriptor(
        name="users",
        bindings=(
            IRProviderBinding(provider="password", identifier="email"),
            IRProviderBinding(
                provider="keycloak", identifier="email",
                claim_mapping={"email": "email"}, auto_provision=True,
            ),
        ),
        id_field="id",
    )


_COLLECTIONS = {
    "users": RuntimeCollectionDescriptor(
        name="users", type="auth", id_field="id", id_format="uuidv7", fields={}
    )
}


async def _resolve(token: str, providers):
    headers = {"Authorization": f"Bearer {token}"}
    return await _resolve_identity_principal(
        identity_collections={"users": _identity()},
        identity_id_fields={"users": "id"},
        registry=_registry(),
        providers=providers,
        collections=_COLLECTIONS,
        headers=headers,
    )


def test_has_idp_provider_detects_idp_trust():
    assert _has_idp_provider({"keycloak": _idp_provider()}) is True


def test_has_idp_provider_false_without_idp():
    app_provider = IROIDCProvider(
        name="google", client_id="c", trust="app", discovery_url=_DISCOVERY_URL
    )
    assert _has_idp_provider({"google": app_provider}) is False


async def test_untrusted_issuer_is_rejected():
    token = jwt.encode(
        {"iss": "https://evil/realms/x", "sub": "x", "exp": int(time.time()) + 300},
        "secret", algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError):
        await _resolve(token, {"keycloak": _idp_provider()})


async def test_opaque_bearer_without_issuer_is_not_rejected():
    principal = await _resolve("opaque-api-key", {"keycloak": _idp_provider()})
    assert principal is None


async def test_issuer_bearing_token_ignored_when_no_idp_provider():
    """Without any idp provider, an iss-bearing bearer is not rejected as untrusted."""
    app_provider = IROIDCProvider(
        name="google", client_id="c", trust="app", discovery_url=_DISCOVERY_URL
    )
    token = jwt.encode(
        {"iss": "https://evil/realms/x", "sub": "x", "exp": int(time.time()) + 300},
        "secret", algorithm="HS256",
    )
    principal = await _resolve(token, {"google": app_provider})
    assert principal is None
