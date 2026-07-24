"""Cookie (BFF) session delivery, CSRF double-submit, and default byte-identity."""

import importlib.util
import types

import pytest

from yaml_api_generator.generators.backend.builders.settings_builder import (
    build_settings_fields,
)
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
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
        assert '"token": token' in out["login"]
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
    def test_login_sets_cookies_and_omits_body_token(self, cookie_ctx, tmp_path):
        FastAPIGenerator().generate(cookie_ctx, tmp_path)
        login = (tmp_path / "routes" / "login.py").read_text()
        assert "set_session_cookies(response, request, token, csrf_token)" in login
        assert '"token": token' not in login
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
