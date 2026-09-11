"""JWKS and discovery caching exercised against the real fetch paths.

The idp trust tests stub the signing-key lookup away; these drive the unpatched
code through an httpx.MockTransport so the cache, its time-to-live, its bound
and the kid-rotation refetch are actually covered — in the dev server and in the
copy vendored into generated FastAPI backends alike.
"""

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from yaml_api_generator.generators.backend.fastapi.static import idp_auth
from yaml_api_generator.server.common.auth import idp, oidc

_ISSUER = "https://kc.test/realms/main"
_JWKS_URI = "https://kc.test/jwks"
_DISCOVERY_URL = "https://kc.test/.well-known/openid-configuration"
_DISCOVERY_DOCUMENT = {"issuer": _ISSUER, "jwks_uri": _JWKS_URI}

_PUBLIC_JWK = RSAAlgorithm.to_jwk(
    rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key(),
    as_dict=True,
)


class _FakeIdP:
    """Serves discovery and JWKS documents over httpx, recording every request."""

    def __init__(self, monkeypatch):
        self.requests: list[str] = []
        self.kids = ["key-1"]
        real_client = httpx.AsyncClient
        transport = httpx.MockTransport(self._respond)
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda **kwargs: real_client(transport=transport, **kwargs),
        )

    def _respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json=_DISCOVERY_DOCUMENT)
        keys = [{**_PUBLIC_JWK, "kid": kid, "alg": "RS256", "use": "sig"} for kid in self.kids]
        return httpx.Response(200, json={"keys": keys})


@pytest.fixture
def fake_idp(monkeypatch):
    return _FakeIdP(monkeypatch)


@pytest.fixture(params=[idp, idp_auth], ids=["dev_server", "vendored"])
def jwks_module(request, monkeypatch):
    module = request.param
    monkeypatch.setattr(module, "_jwks_cache", module.TTLCache())
    return module


@pytest.fixture(params=[oidc, idp_auth], ids=["dev_server", "vendored"])
def discovery_module(request, monkeypatch):
    module = request.param
    monkeypatch.setattr(module, "_discovery_cache", module.TTLCache())
    return module


async def test_jwks_fetched_once_then_served_from_cache(jwks_module, fake_idp):
    first = await jwks_module._get_signing_key(_JWKS_URI, "key-1")
    second = await jwks_module._get_signing_key(_JWKS_URI, "key-1")

    assert first is not None and second is not None
    assert fake_idp.requests == [_JWKS_URI]


async def test_rotated_kid_triggers_exactly_one_refetch(jwks_module, fake_idp):
    await jwks_module._get_signing_key(_JWKS_URI, "key-1")
    fake_idp.kids = ["key-1", "key-2"]

    rotated = await jwks_module._get_signing_key(_JWKS_URI, "key-2")

    assert rotated is not None
    assert fake_idp.requests == [_JWKS_URI, _JWKS_URI]


async def test_kid_still_unknown_after_refetch_yields_no_key(jwks_module, fake_idp):
    await jwks_module._get_signing_key(_JWKS_URI, "key-1")

    assert await jwks_module._get_signing_key(_JWKS_URI, "withdrawn") is None
    assert fake_idp.requests == [_JWKS_URI, _JWKS_URI]


async def test_missing_kid_header_never_reaches_the_network(jwks_module, fake_idp):
    assert await jwks_module._get_signing_key(_JWKS_URI, None) is None
    assert fake_idp.requests == []


async def test_jwks_entry_older_than_the_ttl_is_refetched(jwks_module, fake_idp, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(
        jwks_module, "_jwks_cache", jwks_module.TTLCache(ttl=300.0, clock=lambda: now[0])
    )

    await jwks_module._get_signing_key(_JWKS_URI, "key-1")
    now[0] = 301.0
    await jwks_module._get_signing_key(_JWKS_URI, "key-1")

    assert fake_idp.requests == [_JWKS_URI, _JWKS_URI]


async def test_jwks_cache_does_not_grow_without_bound(jwks_module, fake_idp, monkeypatch):
    monkeypatch.setattr(jwks_module, "_jwks_cache", jwks_module.TTLCache(max_entries=2))

    for index in range(5):
        await jwks_module._get_signing_key(f"https://kc.test/jwks/{index}", "key-1")

    assert len(jwks_module._jwks_cache) == 2


async def test_discovery_fetched_once_then_served_from_cache(discovery_module, fake_idp):
    first = await discovery_module._discovery(_DISCOVERY_URL)
    second = await discovery_module._discovery(_DISCOVERY_URL)

    assert first == second == _DISCOVERY_DOCUMENT
    assert fake_idp.requests == [_DISCOVERY_URL]


async def test_discovery_entry_older_than_the_ttl_is_refetched(
    discovery_module, fake_idp, monkeypatch
):
    now = [0.0]
    monkeypatch.setattr(
        discovery_module,
        "_discovery_cache",
        discovery_module.TTLCache(ttl=300.0, clock=lambda: now[0]),
    )

    await discovery_module._discovery(_DISCOVERY_URL)
    now[0] = 301.0
    await discovery_module._discovery(_DISCOVERY_URL)

    assert fake_idp.requests == [_DISCOVERY_URL, _DISCOVERY_URL]


async def test_discovery_cache_does_not_grow_without_bound(
    discovery_module, fake_idp, monkeypatch
):
    monkeypatch.setattr(
        discovery_module, "_discovery_cache", discovery_module.TTLCache(max_entries=2)
    )

    for index in range(5):
        await discovery_module._discovery(
            f"https://kc.test/{index}/.well-known/openid-configuration"
        )

    assert len(discovery_module._discovery_cache) == 2
