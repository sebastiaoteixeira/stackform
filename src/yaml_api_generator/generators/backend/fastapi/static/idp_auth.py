"""IdP token verification for generated backends (trust: idp).

Tokens issued by an external IdP are verified against that IdP's JWKS on every
request. The app never mints a session token for idp-trust providers; the
original bearer token is the session.

Discovery documents and JWKS clients are cached in-process so that only the
first request per provider hits the network.

The issuer is read from the IdP's discovery document, so it never needs to be
declared in the spec. When no audience override is given, the token's aud is
verified against client_id (correct for ID tokens on Google, Azure, and standard
Keycloak).
"""

import httpx
import jwt

_discovery_cache: dict[str, dict] = {}
_jwks_cache: dict[str, jwt.PyJWKSet] = {}


def unverified_issuer(token: str) -> str | None:
    try:
        return jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.InvalidTokenError:
        return None


async def _discovery(url: str) -> dict:
    if url not in _discovery_cache:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            _discovery_cache[url] = resp.json()
    return _discovery_cache[url]


async def fetch_issuer(discovery_url: str) -> str:
    doc = await _discovery(discovery_url)
    issuer = doc.get("issuer")
    if not issuer:
        raise ValueError(f"No issuer in discovery document: {discovery_url}")
    return issuer


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


async def verify_idp_token(
    token: str,
    *,
    discovery_url: str,
    client_id: str,
    issuer: str | None = None,
    audiences: list[str] | None = None,
) -> dict | None:
    try:
        doc = await _discovery(discovery_url)
        jwks_uri = doc.get("jwks_uri")
        if not jwks_uri:
            return None
        expected_issuer = issuer or doc.get("issuer")
        accepted_audiences = audiences if audiences else [client_id]
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
