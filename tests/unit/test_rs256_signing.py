"""RS256 app-token signing, JWKS exposure, and HS256 default preservation."""

import importlib.util
import sys

import jwt as pyjwt
import pytest

from yaml_api_generator.generators.backend.builders.settings_builder import (
    build_settings_fields,
    generated_secret_values,
)
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from tests.conftest import VALID_DIR


def _ctx(name: str):
    return build_context(load_and_generate_ir(str(VALID_DIR / name)).ir)


@pytest.fixture
def hs_ctx():
    return _ctx("auth-password.yaml")


@pytest.fixture
def rs_ctx():
    return _ctx("auth-password-rs256.yaml")


class TestSessionParsing:
    def test_default_algorithm_is_hs256(self):
        ir = load_and_generate_ir(str(VALID_DIR / "auth-password.yaml")).ir
        assert ir.session.algorithm == "HS256"

    def test_rs256_algorithm_parsed(self):
        ir = load_and_generate_ir(str(VALID_DIR / "auth-password-rs256.yaml")).ir
        assert ir.session.algorithm == "RS256"

    def test_algorithm_flows_into_compile_context(self, rs_ctx):
        assert rs_ctx.session.algorithm == "RS256"
        assert rs_ctx.session.uses_asymmetric is True

    def test_invalid_algorithm_rejected(self, tmp_path):
        spec = tmp_path / "api.yaml"
        spec.write_text(
            (VALID_DIR / "auth-password.yaml").read_text()
            + "session:\n  algorithm: ES512\n"
        )
        with pytest.raises(ConfigErrors):
            load_and_generate_ir(str(spec))


class TestSettings:
    def test_hs256_uses_shared_secret(self, hs_ctx):
        names = {f.env_name for f in build_settings_fields(hs_ctx)}
        assert "JWT_SECRET" in names
        assert "JWT_PRIVATE_KEY" not in names

    def test_rs256_uses_private_key(self, rs_ctx):
        names = {f.env_name for f in build_settings_fields(rs_ctx)}
        assert "JWT_PRIVATE_KEY" in names
        assert "JWT_SECRET" not in names

    def test_generated_private_key_is_quoted_pem(self, rs_ctx):
        fields = build_settings_fields(rs_ctx)
        value = generated_secret_values(fields)["JWT_PRIVATE_KEY"]
        assert value.startswith('"') and value.endswith('"')
        pem = value[1:-1].replace("\\n", "\n")
        assert "BEGIN PRIVATE KEY" in pem


class TestFastAPIGeneration:
    def test_jwks_route_emitted_only_for_rs256(self, hs_ctx, rs_ctx, tmp_path):
        hs_dir, rs_dir = tmp_path / "hs", tmp_path / "rs"
        FastAPIGenerator().generate(hs_ctx, hs_dir)
        FastAPIGenerator().generate(rs_ctx, rs_dir)
        assert (rs_dir / "routes" / "jwks.py").exists()
        assert not (hs_dir / "routes" / "jwks.py").exists()

    def test_app_mounts_jwks_router_for_rs256(self, rs_ctx, tmp_path):
        FastAPIGenerator().generate(rs_ctx, tmp_path)
        app_src = (tmp_path / "app.py").read_text()
        assert "from routes.jwks import router as jwks_router" in app_src
        assert "app.include_router(jwks_router)" in app_src

    def test_jwks_route_serves_well_known_path(self, rs_ctx, tmp_path):
        FastAPIGenerator().generate(rs_ctx, tmp_path)
        assert "/.well-known/jwks.json" in (tmp_path / "routes" / "jwks.py").read_text()

    def test_hs256_jwt_utils_unchanged(self, hs_ctx, tmp_path):
        FastAPIGenerator().generate(hs_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "jwt_utils.py").read_text()
        assert 'algorithm="HS256"' in src
        assert "JWT_PRIVATE_KEY" not in src
        assert "public_jwks" not in src


class TestRS256Runtime:
    def test_sign_verify_and_jwks_round_trip(self, rs_ctx, tmp_path, monkeypatch):
        FastAPIGenerator().generate(rs_ctx, tmp_path)
        env_line = next(
            l for l in (tmp_path / ".env").read_text().splitlines()
            if l.startswith("JWT_PRIVATE_KEY=")
        )
        pem = env_line.split("=", 1)[1][1:-1].replace("\\n", "\n")
        monkeypatch.setenv("JWT_PRIVATE_KEY", pem)
        monkeypatch.setenv("JWT_EXPIRATION_HOURS", "24")
        monkeypatch.syspath_prepend(str(tmp_path))

        settings_mod = _load(tmp_path / "settings.py", "settings")
        sys.modules["settings"] = settings_mod
        jw = _load(tmp_path / "dependencies" / "jwt_utils.py", "jwt_utils_rs256")

        token = jw.create_jwt_token("user-1", "user")
        header = pyjwt.get_unverified_header(token)
        assert header["alg"] == "RS256"

        jwks = jw.public_jwks()
        key = jwks["keys"][0]
        assert key["kid"] == header["kid"]

        public_key = pyjwt.PyJWK.from_dict(key).key
        verified = pyjwt.decode(token, public_key, algorithms=["RS256"])
        assert verified["sub"] == "user-1"
        assert jw.decode_jwt_token(token)["sub"] == "user-1"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
