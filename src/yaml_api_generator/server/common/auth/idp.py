"""Resource-server verification of IdP-issued tokens (trust: idp).

Under trust: idp the client keeps carrying the IdP's own token; the app verifies
it against the IdP's JWKS on every request and issues no session of its own.
The issuer is derived from the discovery document, so it never needs to be
declared in the spec. When no audience override is set, the token's aud is
verified against the provider's client_id (correct for ID tokens from Google,
Azure, and standard Keycloak).
"""

import httpx
import jwt

from yaml_api_generator.ir.api import IROIDCProvider
from .oidc import _discovery

_jwks_cache: dict[str, jwt.PyJWKSet] = {}


async def _fetch_jwks(jwks_uri: str) -> jwt.PyJWKSet:
    async with httpx.AsyncClient() as client:
        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        return jwt.PyJWKSet.from_dict(resp.json())


async def _get_signing_key(jwks_uri: str, kid: str | None) -> jwt.PyJWK | None:
    if kid is None:
        return None
    if jwks_uri not in _jwks_cache:
        _jwks_cache[jwks_uri] = await _fetch_jwks(jwks_uri)
    match = next((k for k in _jwks_cache[jwks_uri].keys if k.key_id == kid), None)
    if match is None:
        _jwks_cache[jwks_uri] = await _fetch_jwks(jwks_uri)
        match = next((k for k in _jwks_cache[jwks_uri].keys if k.key_id == kid), None)
    return match


async def issuer_of(provider: IROIDCProvider) -> str:
    if provider.issuer:
        return provider.issuer
    if not provider.discovery_url:
        raise RuntimeError(
            f"Provider '{provider.name}' needs either issuer or discovery_url"
        )
    doc = await _discovery(provider.discovery_url)
    return doc["issuer"]


def unverified_issuer(token: str) -> str | None:
    try:
        return jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.InvalidTokenError:
        return None


async def verify_idp_token(token: str, provider: IROIDCProvider) -> dict | None:
    discovery_url = provider.discovery_url
    if not discovery_url:
        raise RuntimeError(f"Provider '{provider.name}' is missing discovery_url")
    discovery = await _discovery(discovery_url)
    jwks_uri = discovery.get("jwks_uri")
    if not jwks_uri:
        return None
    expected_issuer = provider.issuer or discovery.get("issuer")
    accepted_audiences = list(provider.audiences) if provider.audiences else [provider.client_id]
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        signing_key = await _get_signing_key(jwks_uri, kid)
        if signing_key is None:
            return None
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=accepted_audiences,
            issuer=expected_issuer,
        )
    except jwt.InvalidTokenError:
        return None
