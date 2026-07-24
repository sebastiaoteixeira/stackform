"""Generator tests for trust: idp provider support."""

import pytest

from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from tests.conftest import VALID_DIR


def _ctx_from_fixture(name: str):
    return build_context(load_and_generate_ir(str(VALID_DIR / name)).ir)


@pytest.fixture
def idp_ctx():
    return _ctx_from_fixture("auth-oidc-idp.yaml")


@pytest.fixture
def idp_minimal_ctx():
    return _ctx_from_fixture("auth-oidc-idp-minimal.yaml")


@pytest.fixture
def dual_ctx():
    return _ctx_from_fixture("auth-dual-trust.yaml")


class TestAuthConfigFlags:
    def test_idp_only_has_idp_auth(self, idp_ctx):
        assert idp_ctx.auth.has_idp_auth is True

    def test_idp_only_has_no_app_oidc(self, idp_ctx):
        assert idp_ctx.auth.has_app_oidc_auth is False

    def test_idp_only_does_not_use_jwt(self, idp_ctx):
        assert idp_ctx.auth.uses_jwt is False

    def test_idp_only_has_oidc_auth(self, idp_ctx):
        assert idp_ctx.auth.has_oidc_auth is True

    def test_idp_providers_populated(self, idp_ctx):
        assert len(idp_ctx.auth.idp_providers) == 1
        p = idp_ctx.auth.idp_providers[0]
        assert p.name == "keycloak"
        assert p.issuer == "https://kc.example.com/realms/main"
        assert p.audiences == ("my-app",)
        assert p.client_id == "my-app"

    def test_idp_minimal_provider_has_no_issuer_audience(self, idp_minimal_ctx):
        assert len(idp_minimal_ctx.auth.idp_providers) == 1
        p = idp_minimal_ctx.auth.idp_providers[0]
        assert p.name == "keycloak"
        assert p.issuer is None
        assert p.audiences == ()
        assert p.client_id == "my-app"
        assert p.discovery_url is not None

    def test_dual_trust_has_both_flags(self, dual_ctx):
        assert dual_ctx.auth.has_idp_auth is True
        assert dual_ctx.auth.has_password_auth is True
        assert dual_ctx.auth.uses_jwt is True

    def test_app_oidc_does_not_set_idp_flag(self):
        ctx = _ctx_from_fixture("auth-oidc.yaml")
        assert ctx.auth.has_idp_auth is False
        assert ctx.auth.has_app_oidc_auth is True
        assert ctx.auth.uses_jwt is True


class TestIdpGeneration:
    def test_vendored_idp_auth_emitted(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        assert (tmp_path / "dependencies" / "idp_auth.py").exists()

    def test_vendored_idp_auth_content(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "idp_auth.py").read_text()
        assert "verify_idp_token" in src
        assert "unverified_issuer" in src
        assert "_jwks_cache" in src
        assert "yaml_api_generator" not in src

    def test_vendored_idp_auth_verifies_rs256_and_es256(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "idp_auth.py").read_text()
        assert '"RS256"' in src and '"ES256"' in src

    def test_idp_auth_not_emitted_for_app_trust(self, tmp_path):
        ctx = _ctx_from_fixture("auth-oidc.yaml")
        FastAPIGenerator().generate(ctx, tmp_path)
        assert not (tmp_path / "dependencies" / "idp_auth.py").exists()

    def test_generated_auth_imports_idp_auth(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "from dependencies import idp_auth" in src

    def test_generated_auth_dispatches_by_iss(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "_IDP_ISSUERS" in src
        assert "idp_auth.unverified_issuer" in src
        assert "idp_auth.verify_idp_token" in src
        assert "idp_auth.fetch_issuer" in src

    def test_idp_discovery_url_baked_into_dispatch_table(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "idp_auth.fetch_issuer" in src

    def test_idp_issuer_baked_into_dispatch_table(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "https://kc.example.com/realms/main" in src
        assert "my-app" in src

    def test_idp_minimal_generates_without_issuer_audience(self, tmp_path, idp_minimal_ctx):
        FastAPIGenerator().generate(idp_minimal_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "idp_auth.fetch_issuer" in src
        assert "idp_auth.verify_idp_token" in src
        assert "client_id" in src

    def test_idp_only_does_not_mint_app_token(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "decode_jwt_token" not in src
        assert "create_jwt_token" not in src

    def test_idp_only_no_jwt_utils(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        assert not (tmp_path / "dependencies" / "jwt_utils.py").exists()

    def test_pure_idp_does_not_generate_oidc_routes(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        assert not (tmp_path / "routes" / "oidc_routes.py").exists()

    def test_pure_idp_does_not_generate_login_codes(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        assert not (tmp_path / "dependencies" / "login_codes.py").exists()

    def test_app_oidc_generates_oidc_routes(self, tmp_path):
        ctx = _ctx_from_fixture("auth-oidc.yaml")
        FastAPIGenerator().generate(ctx, tmp_path)
        assert (tmp_path / "routes" / "oidc_routes.py").exists()

    def test_app_oidc_generates_login_codes(self, tmp_path):
        ctx = _ctx_from_fixture("auth-oidc.yaml")
        FastAPIGenerator().generate(ctx, tmp_path)
        assert (tmp_path / "dependencies" / "login_codes.py").exists()

    def test_requirements_includes_pyjwt_crypto(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "requirements.txt").read_text()
        assert "pyjwt[crypto]" in src.lower() or "pyjwt" in src.lower()

    def test_requirements_includes_httpx_for_jwks_discovery(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "requirements.txt").read_text()
        assert "httpx" in src


class TestIdpCallbackGeneration:
    def test_app_callback_has_login_code(self, tmp_path):
        ctx = _ctx_from_fixture("auth-oidc.yaml")
        FastAPIGenerator().generate(ctx, tmp_path)
        src = (tmp_path / "routes" / "oidc_routes.py").read_text()
        assert "issue_login_code" in src
        assert "create_jwt_token" in src
        assert "issue_idp_code" not in src

    def test_app_login_codes_has_no_issue_idp(self, tmp_path):
        ctx = _ctx_from_fixture("auth-oidc.yaml")
        FastAPIGenerator().generate(ctx, tmp_path)
        src = (tmp_path / "dependencies" / "login_codes.py").read_text()
        assert "issue_idp_code" not in src
        assert "issue_idp" not in src

    def test_app_login_codes_redeem_returns_three_tuple(self, tmp_path):
        ctx = _ctx_from_fixture("auth-oidc.yaml")
        FastAPIGenerator().generate(ctx, tmp_path)
        src = (tmp_path / "dependencies" / "login_codes.py").read_text()
        assert "str | None, str | None, None" in src

    def test_idp_auth_py_uses_audiences_list(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert '"audiences"' in src
        assert '"audience"' not in src

    def test_idp_verify_passes_audiences_kwarg(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "audiences=audiences" in src


class TestDualTrustGeneration:
    def test_dual_trust_emits_idp_auth(self, tmp_path, dual_ctx):
        FastAPIGenerator().generate(dual_ctx, tmp_path)
        assert (tmp_path / "dependencies" / "idp_auth.py").exists()

    def test_dual_trust_emits_jwt_utils(self, tmp_path, dual_ctx):
        FastAPIGenerator().generate(dual_ctx, tmp_path)
        assert (tmp_path / "dependencies" / "jwt_utils.py").exists()

    def test_dual_trust_auth_has_both_paths(self, tmp_path, dual_ctx):
        FastAPIGenerator().generate(dual_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "idp_auth.unverified_issuer" in src
        assert "decode_jwt_token" in src

    def test_dual_trust_iss_dispatch_strict(self, tmp_path, dual_ctx):
        """In resolve_principal, idp iss dispatch must precede the app-JWT decode path."""
        FastAPIGenerator().generate(dual_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        resolve_principal_body = src[src.index("async def resolve_principal"):]
        idp_pos = resolve_principal_body.index("_find_idp_provider_for_issuer")
        jwt_pos = resolve_principal_body.index("decode_jwt_token")
        assert idp_pos < jwt_pos

    def test_dual_trust_rejects_untrusted_issuer(self, tmp_path, dual_ctx):
        """A bearer JWT whose iss matches no trusted issuer is rejected, never retried."""
        FastAPIGenerator().generate(dual_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        resolve_principal_body = src[src.index("async def resolve_principal"):]
        reject_pos = resolve_principal_body.index("Untrusted token issuer")
        jwt_pos = resolve_principal_body.index("decode_jwt_token")
        assert reject_pos < jwt_pos

    def test_pure_idp_rejects_untrusted_issuer(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "Untrusted token issuer" in src
