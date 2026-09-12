"""Cookie (BFF) session delivery, CSRF double-submit, and default byte-identity."""

import importlib.util
import types
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI

from yaml_api_generator.generators.backend.builders.settings_builder import (
    build_settings_fields,
)
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.generators.frontend.packs.loader import load_pack
from yaml_api_generator.generators.frontend.renderer import render_templates
from yaml_api_generator.ir.api import IRSAMLProvider
from yaml_api_generator.parsers.ui_parser import build_generator_context
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.server.common.auth.password import hash_password
from yaml_api_generator.server.common.auth.login_codes import login_codes
from yaml_api_generator.server.common.auth.session_tokens import SessionTokens
from yaml_api_generator.server.common.context_builder import build_runtime_context
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.fastapi.factory import (
    register_fastapi_routes,
    register_provider_routes,
)
from yaml_api_generator.server.fastapi.server import _csrf_middleware
from tests.unit.support.repositories import InMemoryRepository
from tests.conftest import VALID_DIR


def _ctx(name: str):
    return build_context(load_and_generate_ir(str(VALID_DIR / name)).ir)


@pytest.fixture
def plain_ctx():
    return _ctx("auth-password.yaml")


@pytest.fixture
def cookie_ctx():
    return _ctx("auth-password-cookie.yaml")


@pytest.fixture
def cookie_refresh_ctx():
    return _ctx("auth-password-cookie-refresh.yaml")


class TestSessionParsing:
    def test_delivery_defaults_to_token_url(self):
        ir = load_and_generate_ir(str(VALID_DIR / "auth-password.yaml")).ir
        assert ir.session.delivery == "token-url"

    def test_cookie_delivery_parsed(self):
        ir = load_and_generate_ir(str(VALID_DIR / "auth-password-cookie.yaml")).ir
        assert ir.session.delivery == "cookie"

    def test_unimplemented_code_delivery_is_rejected(self, tmp_path):
        source = (VALID_DIR / "auth-password-cookie.yaml").read_text()
        spec = tmp_path / "unsupported-code-delivery.yaml"
        spec.write_text(source.replace("delivery: cookie", "delivery: code"))

        with pytest.raises(ConfigErrors):
            load_and_generate_ir(str(spec))

    def test_flows_into_compile_context(self, cookie_ctx, plain_ctx):
        assert cookie_ctx.session.uses_cookie is True
        assert plain_ctx.session.uses_cookie is False


class TestSettingsUnchanged:
    def test_cookie_adds_no_new_settings(self, plain_ctx, cookie_ctx):
        plain = {f.env_name for f in build_settings_fields(plain_ctx)}
        cookie = {f.env_name for f in build_settings_fields(cookie_ctx)}
        assert plain == cookie


class TestByteIdentity:
    def _files(self, ctx, tmp_path):
        FastAPIGenerator().generate(ctx, tmp_path)
        return {
            "login": (tmp_path / "routes" / "login.py").read_text(),
            "app": (tmp_path / "app.py").read_text(),
            "auth": (tmp_path / "dependencies" / "auth.py").read_text(),
        }

    def test_token_url_default_is_byte_identical(self, plain_ctx, tmp_path):
        out = self._files(plain_ctx, tmp_path)
        assert "set_session_cookies" not in out["login"]
        assert 'return {**session, "user": safe_user}' in out["login"]
        assert "csrf_valid" not in out["app"]
        assert "_CsrfMiddleware" not in out["app"]
        assert "session_token_from_request" not in out["auth"]

    def test_session_cookie_module_only_when_cookie(self, plain_ctx, cookie_ctx, tmp_path):
        plain_dir, cookie_dir = tmp_path / "off", tmp_path / "on"
        FastAPIGenerator().generate(plain_ctx, plain_dir)
        FastAPIGenerator().generate(cookie_ctx, cookie_dir)
        assert (cookie_dir / "dependencies" / "session_cookie.py").exists()
        assert not (plain_dir / "dependencies" / "session_cookie.py").exists()


class TestCookieGeneration:
    @pytest.mark.parametrize("generator", [DRFGenerator(), RawASGIGenerator()])
    def test_unsupported_backends_reject_cookie_delivery(
        self, generator, cookie_ctx, tmp_path
    ):
        with pytest.raises(ConfigErrors) as error:
            generator.generate(cookie_ctx, tmp_path)

        assert [item.code for item in error.value.errors] == [
            "BACKEND_FEATURE_UNSUPPORTED"
        ]
        assert error.value.errors[0].path == "session.delivery"

    def test_login_sets_cookies_and_omits_body_token(self, cookie_ctx, tmp_path):
        FastAPIGenerator().generate(cookie_ctx, tmp_path)
        login = (tmp_path / "routes" / "login.py").read_text()
        assert 'set_session_cookies(response, request, session["token"], csrf_token)' in login
        assert 'return {**session, "user": safe_user}' not in login
        assert '"csrf_token": csrf_token' in login

    def test_csrf_middleware_wired(self, cookie_ctx, tmp_path):
        FastAPIGenerator().generate(cookie_ctx, tmp_path)
        app = (tmp_path / "app.py").read_text()
        assert "class _CsrfMiddleware" in app
        assert "app.add_middleware(_CsrfMiddleware)" in app
        assert "CSRF token missing or invalid" in app

    def test_auth_reads_session_cookie(self, cookie_ctx, tmp_path):
        FastAPIGenerator().generate(cookie_ctx, tmp_path)
        auth = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "session_token_from_request(request)" in auth

    def test_refresh_reads_cookie_not_body(self, cookie_refresh_ctx, tmp_path):
        FastAPIGenerator().generate(cookie_refresh_ctx, tmp_path)
        login = (tmp_path / "routes" / "login.py").read_text()
        assert "refresh_token_from_request(request)" in login
        assert "class RefreshPayload" not in login
        assert "REFRESH_COOKIE" in (tmp_path / "dependencies" / "session_cookie.py").read_text()

    def test_logout_route_clears_all_cookies(self, cookie_refresh_ctx, tmp_path):
        FastAPIGenerator().generate(cookie_refresh_ctx, tmp_path)
        route = (tmp_path / "routes" / "session.py").read_text()
        helper = (tmp_path / "dependencies" / "session_cookie.py").read_text()

        assert '@router.post("/auth/logout", status_code=204)' in route
        assert "clear_session_cookies(response)" in route
        assert "response.delete_cookie(SESSION_COOKIE" in helper
        assert "response.delete_cookie(REFRESH_COOKIE" in helper
        assert "response.delete_cookie(CSRF_COOKIE" in helper

    def test_oidc_exchange_delivers_cookie_without_body_token(self, tmp_path):
        ir = load_and_generate_ir(str(VALID_DIR / "auth-oidc.yaml")).ir
        ir = replace(ir, session=replace(ir.session, delivery="cookie"))
        FastAPIGenerator().generate(build_context(ir), tmp_path)
        oidc = (tmp_path / "routes" / "oidc_routes.py").read_text()

        assert 'response = JSONResponse({"csrf_token": csrf_token})' in oidc
        assert 'set_session_cookies(response, request, session["token"], csrf_token)' in oidc
        assert "return session" not in oidc

    def test_saml_callback_delivers_cookie_without_body_token(
        self, cookie_ctx, tmp_path
    ):
        identity = cookie_ctx.auth.identity_collections[0]
        binding = replace(identity.bindings[0], provider="corporate-saml")
        saml_identity = replace(identity, bindings=[binding])
        saml_auth = replace(
            cookie_ctx.auth,
            identity_collections=[saml_identity],
            has_password_auth=False,
            has_saml_auth=True,
            providers={
                "corporate-saml": IRSAMLProvider(
                    name="corporate-saml",
                    idp_metadata_url="https://idp.example.test/metadata",
                    sp_entity_id="urn:example:app",
                )
            },
        )
        FastAPIGenerator().generate(replace(cookie_ctx, auth=saml_auth), tmp_path)
        saml = (tmp_path / "routes" / "saml_routes.py").read_text()

        compile(saml, "saml_routes.py", "exec")
        assert 'response = JSONResponse({"user": user, "csrf_token": csrf_token})' in saml
        assert 'set_session_cookies(response, request, session["token"], csrf_token)' in saml
        assert 'return {**session, "user": user}' not in saml

    def test_generic_frontend_uses_cookie_transport_and_server_logout(self):
        ir = load_and_generate_ir(str(VALID_DIR / "auth-password-cookie.yaml")).ir
        pack = load_pack("generic")
        ui = build_generator_context(ir, {}, pack.manifest)
        files = {item.path: item.content for item in render_templates(pack, ui)}
        app = files["src/__generated__/App.tsx"]
        main = files["src/__generated__/main.tsx"]

        assert "credentials: 'include'" in main
        assert "headers.set('x-csrf-token'" in main
        assert "localStorage.setItem('token'" not in app
        assert "await fetch(`${API_BASE_URL}/auth/logout`" in app
        assert "onToken('cookie-session')" in app


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(method: str, cookies: dict, headers: dict):
    return types.SimpleNamespace(
        method=method,
        cookies=cookies,
        headers=types.SimpleNamespace(get=lambda k, default=None: headers.get(k, default)),
    )


class TestCsrfRuntime:
    def _module(self, cookie_ctx, tmp_path):
        FastAPIGenerator().generate(cookie_ctx, tmp_path)
        return _load(tmp_path / "dependencies" / "session_cookie.py", "session_cookie_x")

    def test_safe_methods_pass(self, cookie_ctx, tmp_path):
        mod = self._module(cookie_ctx, tmp_path)
        assert mod.csrf_valid(_request("GET", {"session": "s"}, {})) is True

    def test_no_session_cookie_passes(self, cookie_ctx, tmp_path):
        mod = self._module(cookie_ctx, tmp_path)
        assert mod.csrf_valid(_request("POST", {}, {})) is True

    def test_matching_double_submit_passes(self, cookie_ctx, tmp_path):
        mod = self._module(cookie_ctx, tmp_path)
        req = _request("POST", {"session": "s", "csrf_token": "abc"}, {"x-csrf-token": "abc"})
        assert mod.csrf_valid(req) is True

    def test_missing_header_rejected(self, cookie_ctx, tmp_path):
        mod = self._module(cookie_ctx, tmp_path)
        req = _request("POST", {"session": "s", "csrf_token": "abc"}, {})
        assert mod.csrf_valid(req) is False

    def test_mismatched_token_rejected(self, cookie_ctx, tmp_path):
        mod = self._module(cookie_ctx, tmp_path)
        req = _request("POST", {"session": "s", "csrf_token": "abc"}, {"x-csrf-token": "nope"})
        assert mod.csrf_valid(req) is False

    def test_refresh_cookie_without_session_still_requires_csrf(
        self, cookie_refresh_ctx, tmp_path
    ):
        mod = self._module(cookie_refresh_ctx, tmp_path)
        req = _request(
            "POST",
            {"refresh_token": "refresh", "csrf_token": "abc"},
            {},
        )
        assert mod.csrf_valid(req) is False


def _runtime_app(fixture_name: str) -> FastAPI:
    ir = load_and_generate_ir(str(VALID_DIR / fixture_name)).ir
    ctx = build_runtime_context(ir)
    repo = InMemoryRepository(
        {
            "users": [
                {
                    "id": "user-1",
                    "email": "a@b.com",
                    "name": "Alice",
                    "_auth": {"passwordHash": hash_password("secret123")},
                }
            ]
        }
    )
    repo.register_id_field("users", "id")
    app = FastAPI()
    app.add_middleware(_csrf_middleware())
    register_fastapi_routes(app, ctx, RepositoryRegistry.single(repo))
    return app


class TestDevServerCookieFlow:
    @pytest.mark.asyncio
    async def test_oidc_exchange_sets_cookie_without_exposing_token(self):
        ir = load_and_generate_ir(str(VALID_DIR / "auth-oidc.yaml")).ir
        ir = replace(ir, session=replace(ir.session, delivery="cookie"))
        ctx = build_runtime_context(ir)
        app = FastAPI()
        register_provider_routes(
            app,
            ctx,
            RepositoryRegistry.single(InMemoryRepository()),
            SessionTokens(ctx.session),
        )
        code = login_codes.issue("user-1", "users")
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/auth/exchange", json={"code": code}
            )

            assert response.status_code == 200
            assert "token" not in response.json()
            assert response.json()["csrf_token"] == client.cookies["csrf_token"]
            assert client.cookies.get("session")

    @pytest.mark.asyncio
    async def test_login_uses_http_only_cookie_and_cookie_authenticates(self):
        transport = httpx.ASGITransport(app=_runtime_app("auth-password-cookie.yaml"))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
            "/api/v1/users/login",
            json={"email": "a@b.com", "password": "secret123"},
            )

            assert login.status_code == 200
            assert "token" not in login.json()
            assert login.json()["csrf_token"] == client.cookies["csrf_token"]
            assert "HttpOnly" in login.headers["set-cookie"]
            assert client.cookies.get("session")
            assert (await client.get("/api/v1/users")).status_code == 200

    @pytest.mark.asyncio
    async def test_unsafe_cookie_request_requires_double_submit(self):
        transport = httpx.ASGITransport(app=_runtime_app("auth-password-cookie.yaml"))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
            "/api/v1/users/login",
            json={"email": "a@b.com", "password": "secret123"},
            )
            rejected = await client.post(
            "/api/v1/users",
            json={"email": "new@example.com", "name": "New", "password": "secret123"},
            )
            accepted = await client.post(
            "/api/v1/users",
            headers={"x-csrf-token": client.cookies["csrf_token"]},
            json={"email": "new@example.com", "name": "New", "password": "secret123"},
            )

            assert rejected.status_code == 403
            assert accepted.status_code != 403

    @pytest.mark.asyncio
    async def test_refresh_cookie_remains_csrf_protected_after_session_expires(self):
        transport = httpx.ASGITransport(app=_runtime_app("auth-password-cookie-refresh.yaml"))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
            "/api/v1/users/login",
            json={"email": "a@b.com", "password": "secret123"},
            )
            old_refresh = client.cookies["refresh_token"]
            csrf_token = login.json()["csrf_token"]
            client.cookies.delete("session")

            rejected = await client.post("/api/v1/users/refresh")
            rotated = await client.post(
            "/api/v1/users/refresh",
            headers={"x-csrf-token": csrf_token},
            )

            assert rejected.status_code == 403
            assert rotated.status_code == 200
            assert "token" not in rotated.json()
            assert client.cookies["refresh_token"] != old_refresh
            assert client.cookies.get("session")

    @pytest.mark.asyncio
    async def test_logout_requires_csrf_and_clears_all_session_cookies(self):
        transport = httpx.ASGITransport(app=_runtime_app("auth-password-cookie-refresh.yaml"))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
            "/api/v1/users/login",
            json={"email": "a@b.com", "password": "secret123"},
            )
            csrf_token = login.json()["csrf_token"]

            assert (await client.post("/api/v1/auth/logout")).status_code == 403
            logout = await client.post(
            "/api/v1/auth/logout",
            headers={"x-csrf-token": csrf_token},
            )

            assert logout.status_code == 204
            assert not any(
                client.cookies.get(name)
                for name in ("session", "refresh_token", "csrf_token")
            )
