"""Resource-server verification of IdP-issued tokens (trust: idp).

Under trust: idp the client keeps carrying the IdP's own token; the app verifies
it against the IdP's JWKS on every request and issues no session of its own.
Signing keys are fetched once per JWKS URI and cached by PyJWT's client.
"""

import jwt

from yaml_api_generator.ir.api import IROIDCProvider
from .oidc import _discovery, _resolve

_jwks_clients: dict[str, jwt.PyJWKClient] = {}


def issuer_of(provider: IROIDCProvider) -> str:
    return _resolve(provider.issuer)


def unverified_issuer(token: str) -> str | None:
    try:
        return jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.InvalidTokenError:
        return None


def _discovery_url(provider: IROIDCProvider) -> str:
    if provider.discovery_url is not None:
        return _resolve(provider.discovery_url)
    return f"{issuer_of(provider).rstrip('/')}/.well-known/openid-configuration"


async def verify_idp_token(token: str, provider: IROIDCProvider) -> dict | None:
    discovery = await _discovery(_discovery_url(provider))
    jwks_uri = discovery.get("jwks_uri")
    if not jwks_uri:
        return None
    client = _jwks_clients.setdefault(jwks_uri, jwt.PyJWKClient(jwks_uri))
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=_resolve(provider.audience),
            issuer=issuer_of(provider),
        )
    except jwt.InvalidTokenError:
        return None
