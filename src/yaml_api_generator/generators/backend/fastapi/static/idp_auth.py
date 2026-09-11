"""IdP token verification for generated FastAPI backends (trust: idp).

Tokens issued by an external IdP are verified against that IdP's JWKS on every
request. The app never mints a session token for idp-trust providers; the
original bearer token is the session.

Discovery documents and key sets are cached in-process behind a bounded,
expiring cache, so that a key withdrawn at the IdP stops verifying tokens once
its entry ages out.

The issuer is read from the IdP's discovery document, so it never needs to be
declared in the spec. When no audience override is given, the token's aud is
verified against client_id (correct for ID tokens on Google, Azure, and standard
Keycloak).

A token whose header carries no kid cannot be matched against the JWKS and is
rejected. Only jwt.InvalidTokenError means "invalid token": an unreachable IdP
propagates as a transport error rather than an authentication failure.
"""

import time
from collections import OrderedDict
from collections.abc import Callable, Iterator, MutableMapping
from contextlib import suppress
from typing import TypeVar

import httpx
import jwt

CACHE_TTL_SECONDS = 300.0
CACHE_MAX_ENTRIES = 128
REQUIRED_CLAIMS = ["exp", "iss", "aud", "sub"]

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(MutableMapping[K, V]):
    """Bounded mapping whose entries expire after a fixed time-to-live."""

    def __init__(
        self,
        ttl: float = CACHE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def _drop_expired(self) -> None:
        now = self._clock()
        for key in [k for k, (expires_at, _) in self._entries.items() if expires_at <= now]:
            del self._entries[key]

    def __getitem__(self, key: K) -> V:
        self._drop_expired()
        _, value = self._entries[key]
        self._entries.move_to_end(key)
        return value

    def __setitem__(self, key: K, value: V) -> None:
        self._drop_expired()
        self._entries[key] = (self._clock() + self._ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def __delitem__(self, key: K) -> None:
        del self._entries[key]

    def __iter__(self) -> Iterator[K]:
        self._drop_expired()
        return iter(self._entries)

    def __len__(self) -> int:
        self._drop_expired()
        return len(self._entries)


_discovery_cache: TTLCache[str, dict] = TTLCache()
_jwks_cache: TTLCache[str, jwt.PyJWKSet] = TTLCache()
_ASYMMETRIC_ALGORITHMS = ["RS256", "ES256"]


def unverified_issuer(token: str) -> str | None:
    try:
        return jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.InvalidTokenError:
        return None


async def _discovery(url: str) -> dict:
    cached = _discovery_cache.get(url)
    if cached is not None:
        return cached
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
    document = resp.json()
    _discovery_cache[url] = document
    return document


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
    cached = _jwks_cache.get(jwks_uri)
    if cached is not None:
        with suppress(KeyError):
            return cached[kid]
    rotated = _jwks_cache[jwks_uri] = await _fetch_jwks(jwks_uri)
    with suppress(KeyError):
        return rotated[kid]
    return None


async def verify_idp_token(
    token: str,
    *,
    discovery_url: str,
    client_id: str,
    issuer: str | None = None,
    audiences: list[str] | None = None,
) -> dict | None:
    doc = await _discovery(discovery_url)
    jwks_uri = doc.get("jwks_uri")
    if not jwks_uri:
        return None
    expected_issuer = issuer or doc.get("issuer")
    accepted_audiences = audiences if audiences else [client_id]
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        signing_key = await _get_signing_key(jwks_uri, kid)
        if signing_key is None:
            return None
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=_ASYMMETRIC_ALGORITHMS,
            audience=accepted_audiences,
            issuer=expected_issuer,
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.InvalidTokenError:
        return None
