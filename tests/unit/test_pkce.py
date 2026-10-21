from dataclasses import replace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI

from tests.conftest import VALID_DIR
from tests.unit.support.repositories import InMemoryRepository
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.server.common.auth import oidc
from yaml_api_generator.server.common.auth.session_tokens import SessionTokens
from yaml_api_generator.server.common.context_builder import build_runtime_context
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.fastapi.factory import register_provider_routes


DISCOVERY_URL = "http://localhost:8080/.well-known/openid-configuration"
DISCOVERY = {
    "authorization_endpoint": "https://idp.example.test/authorize",
    "token_endpoint": "https://idp.example.test/token",
    "userinfo_endpoint": "https://idp.example.test/userinfo",
}
LOGIN_PATH = "/api/v1/users/auth/keycloak"
CALLBACK_PATH = f"{LOGIN_PATH}/callback"
STATE_COOKIE = "users_keycloak_state"
VERIFIER_COOKIE = "users_keycloak_pkce_verifier"


def _ir():
    return load_and_generate_ir(str(VALID_DIR / "auth-oidc-pkce.yaml")).ir


def _runtime_app() -> tuple[FastAPI, InMemoryRepository]:
    ctx = build_runtime_context(_ir())
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    app = FastAPI()
    register_provider_routes(
        app,
        ctx,
        RepositoryRegistry.single(repo),
        SessionTokens(ctx.session),
    )
    oidc._discovery_cache[DISCOVERY_URL] = DISCOVERY
    return app, repo


def test_pkce_reaches_ir():
    assert _ir().providers["keycloak"].pkce is True


def test_generated_fastapi_pkce_sources_compile(tmp_path):
    FastAPIGenerator().generate(build_context(_ir()), tmp_path)

    for source_path in tmp_path.rglob("*.py"):
        compile(source_path.read_text(), str(source_path), "exec")


def test_pkce_is_rejected_for_idp_trust(tmp_path):
    source = (VALID_DIR / "auth-oidc-pkce.yaml").read_text()
    path = tmp_path / "idp-pkce.yaml"
    path.write_text(source.replace("pkce: true", "pkce: true\n    trust: idp"))

    with pytest.raises(ConfigErrors) as raised:
        load_and_generate_ir(str(path))

    assert "SCHEMA_VALIDATION_ERROR" in {
        error.code for error in raised.value.errors
    }


@pytest.mark.parametrize("generator", [DRFGenerator(), RawASGIGenerator()])
def test_unsupported_backends_reject_pkce(generator, tmp_path):
    with pytest.raises(ConfigErrors) as raised:
        generator.generate(build_context(_ir()), tmp_path)

    assert [error.code for error in raised.value.errors] == [
        "BACKEND_FEATURE_UNSUPPORTED"
    ]


@pytest.mark.asyncio
async def test_runtime_login_emits_s256_challenge_and_correlated_state():
    app, _ = _runtime_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.get(LOGIN_PATH, follow_redirects=False)

        assert response.status_code == 307
        params = parse_qs(urlparse(response.headers["location"]).query)
        verifier = client.cookies[VERIFIER_COOKIE]
        assert params["code_challenge_method"] == ["S256"]
        assert params["code_challenge"] == [oidc.pkce_challenge(verifier)]
        assert params["state"] == [client.cookies[STATE_COOKIE]]
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "=" not in params["code_challenge"][0]


@pytest.mark.asyncio
async def test_runtime_callback_requires_state_and_sends_verifier(monkeypatch):
    app, _ = _runtime_app()
    exchange = AsyncMock(return_value={"access_token": "access"})
    monkeypatch.setattr(oidc, "_exchange_code", exchange)
    monkeypatch.setattr(
        oidc,
        "_fetch_userinfo",
        AsyncMock(return_value={"sub": "subject", "email": "a@example.com"}),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        login = await client.get(LOGIN_PATH, follow_redirects=False)
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        verifier = client.cookies[VERIFIER_COOKIE]

        rejected = await client.get(
            CALLBACK_PATH,
            params={"code": "authorization-code", "state": "wrong"},
            follow_redirects=False,
        )
        callback = await client.get(
            CALLBACK_PATH,
            params={"code": "authorization-code", "state": state},
            follow_redirects=False,
        )

        assert rejected.status_code == 400
        assert callback.status_code == 307
        assert exchange.await_args.kwargs["code_verifier"] == verifier
        assert client.cookies.get(STATE_COOKIE) is None
        assert client.cookies.get(VERIFIER_COOKIE) is None


@pytest.mark.asyncio
async def test_runtime_callback_rejects_missing_verifier(monkeypatch):
    app, _ = _runtime_app()
    exchange = AsyncMock(return_value={"access_token": "access"})
    monkeypatch.setattr(oidc, "_exchange_code", exchange)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        login = await client.get(LOGIN_PATH, follow_redirects=False)
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        client.cookies.delete(VERIFIER_COOKIE)
        response = await client.get(
            CALLBACK_PATH,
            params={"code": "authorization-code", "state": state},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Missing PKCE verifier"
        exchange.assert_not_awaited()
