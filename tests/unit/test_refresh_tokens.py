"""Refresh-token rotation, reuse detection, and default-off byte-identity."""

import asyncio
import importlib
import importlib.util
import sys
import types

import pytest

from yaml_api_generator.generators.backend.builders.settings_builder import (
    build_settings_fields,
)
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from tests.conftest import VALID_DIR


def _ctx(name: str):
    return build_context(load_and_generate_ir(str(VALID_DIR / name)).ir)


@pytest.fixture
def plain_ctx():
    return _ctx("auth-password.yaml")


@pytest.fixture
def refresh_ctx():
    return _ctx("auth-password-refresh.yaml")


class TestSessionParsing:
    def test_refresh_defaults_off(self):
        ir = load_and_generate_ir(str(VALID_DIR / "auth-password.yaml")).ir
        assert ir.session.refresh is False
        assert ir.session.ttl is None

    def test_refresh_and_ttl_parsed(self):
        ir = load_and_generate_ir(str(VALID_DIR / "auth-password-refresh.yaml")).ir
        assert ir.session.refresh is True
        assert ir.session.ttl == 900

    def test_flows_into_compile_context(self, refresh_ctx):
        assert refresh_ctx.session.refresh is True
        assert refresh_ctx.session.ttl == 900

    def test_non_integer_ttl_rejected(self, tmp_path):
        spec = tmp_path / "api.yaml"
        spec.write_text(
            (VALID_DIR / "auth-password.yaml").read_text()
            + "session:\n  refresh: true\n  ttl: soon\n"
        )
        with pytest.raises(ConfigErrors):
            load_and_generate_ir(str(spec))


class TestSettings:
    def test_off_keeps_expiration_hours(self, plain_ctx):
        names = {f.env_name for f in build_settings_fields(plain_ctx)}
        assert "JWT_EXPIRATION_HOURS" in names
        assert "JWT_ACCESS_TTL_SECONDS" not in names

    def test_on_emits_ttl_settings(self, refresh_ctx):
        fields = {f.env_name: f for f in build_settings_fields(refresh_ctx)}
        assert "JWT_EXPIRATION_HOURS" not in fields
        assert fields["JWT_ACCESS_TTL_SECONDS"].default == "900"
        assert "JWT_REFRESH_TTL_SECONDS" in fields


class TestGeneration:
    def test_rotation_helpers_emitted_only_when_on(self, plain_ctx, refresh_ctx, tmp_path):
        plain_dir, refresh_dir = tmp_path / "off", tmp_path / "on"
        FastAPIGenerator().generate(plain_ctx, plain_dir)
        FastAPIGenerator().generate(refresh_ctx, refresh_dir)
        on = (refresh_dir / "dependencies" / "session_tokens.py").read_text()
        off = (plain_dir / "dependencies" / "session_tokens.py").read_text()
        assert "rotate_session" in on
        assert "rotate_session" not in off
        assert "_refresh_tokens" not in off

    def test_login_route_off_is_byte_identical(self, plain_ctx, refresh_ctx, tmp_path):
        plain_dir, refresh_dir = tmp_path / "off", tmp_path / "on"
        FastAPIGenerator().generate(plain_ctx, plain_dir)
        FastAPIGenerator().generate(refresh_ctx, refresh_dir)
        plain_login = (plain_dir / "routes" / "login.py").read_text()
        assert "refresh_token" not in plain_login
        assert "/refresh" not in plain_login

    def test_login_route_on_emits_refresh(self, refresh_ctx, tmp_path):
        FastAPIGenerator().generate(refresh_ctx, tmp_path)
        login = (tmp_path / "routes" / "login.py").read_text()
        assert '"/users/refresh"' in login
        assert "refresh_token" in login

    def test_jwt_utils_off_has_no_refresh_helpers(self, plain_ctx, tmp_path):
        FastAPIGenerator().generate(plain_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "jwt_utils.py").read_text()
        assert "create_refresh_token" not in src
        assert "JWT_ACCESS_TTL_SECONDS" not in src


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def find_one(self, query):
        return next(
            (d for d in self.docs if all(d.get(k) == v for k, v in query.items())),
            None,
        )

    async def update_one(self, query, update):
        doc = await self.find_one(query)
        if doc is not None:
            doc.update(update["$set"])

    async def update_many(self, query, update):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                d.update(update["$set"])

    async def find_one_and_update(self, query, update):
        doc = await self.find_one(query)
        if doc is None:
            return None
        before = dict(doc)
        doc.update(update["$set"])
        return before


class TestRotationRuntime:
    def _wire(self, refresh_ctx, tmp_path):
        FastAPIGenerator().generate(refresh_ctx, tmp_path)
        secret = next(
            l.split("=", 1)[1]
            for l in (tmp_path / ".env").read_text().splitlines()
            if l.startswith("JWT_SECRET=")
        )

        class _Secret(str):
            def get_secret_value(self):
                return str(self)

        settings_mod = types.ModuleType("settings")
        settings_mod.settings = types.SimpleNamespace(
            JWT_SECRET=_Secret(secret),
            JWT_ACCESS_TTL_SECONDS=900,
            JWT_REFRESH_TTL_SECONDS=2592000,
        )
        sys.modules["settings"] = settings_mod

        jw = _load(tmp_path / "dependencies" / "jwt_utils.py", "jwt_utils_refresh")
        collection = _FakeCollection()
        deps = types.ModuleType("dependencies")
        deps.__path__ = []
        mongo_mod = types.ModuleType("dependencies.mongodb")
        mongo_mod.get_database = lambda: {"_refresh_tokens": collection}
        sys.modules.update({
            "dependencies": deps,
            "dependencies.jwt_utils": jw,
            "dependencies.mongodb": mongo_mod,
        })
        tokens = _load(
            tmp_path / "dependencies" / "session_tokens.py", "session_tokens_x"
        )
        return tokens, collection, jw

    def test_rotate_issues_new_token(self, refresh_ctx, tmp_path):
        tokens, _, jw = self._wire(refresh_ctx, tmp_path)

        async def scenario():
            first = await tokens.issue_session("user-1", "user")
            rotated = await tokens.rotate_session(first["refresh_token"])
            assert rotated is not None
            assert rotated["refresh_token"] != first["refresh_token"]
            assert jw.decode_jwt_token(rotated["token"])["sub"] == "user-1"
            assert await tokens.rotate_session(rotated["refresh_token"]) is not None

        asyncio.run(scenario())

    def test_reuse_revokes_whole_family(self, refresh_ctx, tmp_path):
        tokens, collection, _ = self._wire(refresh_ctx, tmp_path)

        async def scenario():
            first = await tokens.issue_session("user-1", "user")
            await tokens.rotate_session(first["refresh_token"])
            replay = await tokens.rotate_session(first["refresh_token"])
            assert replay is None
            assert all(d["revoked"] for d in collection.docs)

        asyncio.run(scenario())

    def test_revoked_family_cannot_rotate(self, refresh_ctx, tmp_path):
        tokens, _, _ = self._wire(refresh_ctx, tmp_path)

        async def scenario():
            first = await tokens.issue_session("user-1", "user")
            second = await tokens.rotate_session(first["refresh_token"])
            await tokens.rotate_session(first["refresh_token"])
            assert await tokens.rotate_session(second["refresh_token"]) is None

        asyncio.run(scenario())

    def test_unknown_token_rejected(self, refresh_ctx, tmp_path):
        tokens, _, _ = self._wire(refresh_ctx, tmp_path)
        assert asyncio.run(tokens.rotate_session("not-a-token")) is None

    def test_refresh_token_is_not_accepted_as_access_token(self, refresh_ctx, tmp_path):
        tokens, _, jw = self._wire(refresh_ctx, tmp_path)

        async def scenario():
            issued = await tokens.issue_session("user-1", "user")
            assert jw.decode_refresh_token(issued["refresh_token"]) is not None
            assert jw.decode_jwt_token(issued["refresh_token"]) is None

        asyncio.run(scenario())

    def test_records_carry_an_expiry_for_ttl_cleanup(self, refresh_ctx, tmp_path):
        tokens, collection, _ = self._wire(refresh_ctx, tmp_path)
        asyncio.run(tokens.issue_session("user-1", "user"))
        assert collection.docs[0]["expires_at"] is not None


class TestUnsupportedBackends:
    @pytest.mark.parametrize(
        "generator_path",
        [
            "yaml_api_generator.generators.backend.drf.generator.DRFGenerator",
            "yaml_api_generator.generators.backend.raw.generator.RawASGIGenerator",
        ],
    )
    def test_refresh_is_rejected_loudly(self, refresh_ctx, tmp_path, generator_path):
        module_name, class_name = generator_path.rsplit(".", 1)
        generator = getattr(importlib.import_module(module_name), class_name)()
        with pytest.raises(ConfigErrors) as excinfo:
            generator.generate(refresh_ctx, tmp_path)
        codes = {e.code for e in excinfo.value.errors}
        assert codes == {"BACKEND_FEATURE_UNSUPPORTED"}

    @pytest.mark.parametrize(
        "generator_path",
        [
            "yaml_api_generator.generators.backend.drf.generator.DRFGenerator",
            "yaml_api_generator.generators.backend.raw.generator.RawASGIGenerator",
        ],
    )
    def test_refresh_off_still_generates(self, plain_ctx, tmp_path, generator_path):
        module_name, class_name = generator_path.rsplit(".", 1)
        generator = getattr(importlib.import_module(module_name), class_name)()
        generator.generate(plain_ctx, tmp_path)
        assert any(tmp_path.iterdir())
