"""Generator tests for trust: idp provider support.

The vendored verifier and the generated ``resolve_principal`` are imported from
the generated tree and executed, so the assertions describe behaviour rather
than the shape of the emitted source.
"""

import asyncio
import importlib.util
import json
import subprocess
import sys
import textwrap
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from tests.conftest import VALID_DIR

_DISCOVERY_URL = "https://idp.test/.well-known/openid-configuration"
_ISSUER = "https://idp.test"
_JWKS_URI = "https://idp.test/jwks"
_AUDIENCE = "my-app"
_SUBJECT = "idp-subject"
_RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_EC_KEY = ec.generate_private_key(ec.SECP256R1())


def _ctx_from_fixture(name: str):
    return build_context(load_and_generate_ir(str(VALID_DIR / name)).ir)


def _public_jwk(private_key, algorithm: str, kid: str) -> dict:
    algorithms = jwt.algorithms.get_default_algorithms()
    key = json.loads(algorithms[algorithm].to_jwk(private_key.public_key()))
    return {**key, "kid": kid, "alg": algorithm, "use": "sig"}


def _sign(key, algorithm: str, kid: str) -> str:
    return jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": _SUBJECT,
            "exp": int(time.time()) + 300,
        },
        key,
        algorithm=algorithm,
        headers={"kid": kid},
    )


def _load_vendored_idp_auth(generated_root):
    spec = importlib.util.spec_from_file_location(
        "vendored_idp_auth", generated_root / "dependencies" / "idp_auth.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._discovery_cache[_DISCOVERY_URL] = {"issuer": _ISSUER, "jwks_uri": _JWKS_URI}
    module._jwks_cache[_JWKS_URI] = jwt.PyJWKSet.from_dict(
        {
            "keys": [
                _public_jwk(_RSA_KEY, "RS256", "rsa-1"),
                _public_jwk(_EC_KEY, "ES256", "ec-1"),
            ]
        }
    )
    return module


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
        idp_pos = resolve_principal_body.index("_resolve_idp_principal")
        jwt_pos = resolve_principal_body.index("decode_jwt_token")
        assert idp_pos < jwt_pos

    def test_dual_trust_rejects_untrusted_issuer(self, tmp_path, dual_ctx):
        """A bearer JWT whose iss matches no trusted issuer is rejected, never retried."""
        FastAPIGenerator().generate(dual_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        idp_body = src[
            src.index("async def _resolve_idp_principal"):src.index("async def resolve_principal")
        ]
        assert idp_body.count('detail="Untrusted token issuer"') == 2
        assert "return None" not in idp_body

    def test_pure_idp_rejects_untrusted_issuer(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        src = (tmp_path / "dependencies" / "auth.py").read_text()
        assert "Untrusted token issuer" in src


class TestVendoredIdpAuthVerification:
    """The vendored verifier is loaded from the generated tree and executed."""

    @pytest.fixture
    def idp_auth(self, tmp_path, idp_ctx):
        FastAPIGenerator().generate(idp_ctx, tmp_path)
        return _load_vendored_idp_auth(tmp_path)

    @staticmethod
    def _verify(module, token):
        return asyncio.run(
            module.verify_idp_token(
                token, discovery_url=_DISCOVERY_URL, client_id=_AUDIENCE
            )
        )

    def test_verifies_rs256_token(self, idp_auth):
        claims = self._verify(idp_auth, _sign(_RSA_KEY, "RS256", "rsa-1"))
        assert claims["sub"] == _SUBJECT

    def test_verifies_es256_token(self, idp_auth):
        claims = self._verify(idp_auth, _sign(_EC_KEY, "ES256", "ec-1"))
        assert claims["sub"] == _SUBJECT

    def test_rejects_hs256_token_signed_for_a_jwks_key_id(self, idp_auth):
        forged = _sign("symmetric-secret-long-enough-for-sha256", "HS256", "rsa-1")
        assert self._verify(idp_auth, forged) is None


_BEHAVIOUR_SPEC = """
version: "0.2"
api:
  basePath: /api
  version: v1
providers:
  keycloak:
    type: oidc
    trust: idp
    client_id: my-app
    discovery_url: "http://keycloak.test/.well-known/openid-configuration"
    audiences: ["my-app"]
  okta:
    type: oidc
    trust: idp
    client_id: other-app
    discovery_url: "http://okta.test/.well-known/openid-configuration"
    audiences: ["other-app"]
mongo:
  uri: mongodb://localhost:27017
  database: testdb
entities:
  user:
    type: auth
    auth:
      identifier: email
      via:
        - provider: keycloak
          identifier: email
          claim_mapping:
            email: profile.email
          auto_provision: false
    fields:
      id: { type: id }
      email: { type: string, required: true, unique: true }
      name: { type: string }
repositories:
  users:
    entity: user
services:
  users:
    repository: users
controllers:
  users:
    service: users
    base_path: /users
    access: "*"
"""

_BEHAVIOUR_HARNESS = '''
import asyncio
import json
import sys

sys.path.insert(0, ".")

from fastapi import HTTPException

from dependencies import auth, idp_auth

ISSUER_BY_DISCOVERY_URL = {
    "http://keycloak.test/.well-known/openid-configuration": "https://keycloak.test",
    "http://okta.test/.well-known/openid-configuration": "https://okta.test",
}
NESTED_CLAIMS = {"sub": "user-1", "profile": {"email": "nested@example.com"}}
RECORD = {"id": "user-1", "email": "nested@example.com", "name": "Nested"}


class Cursor:
    def __init__(self, documents):
        self._documents = documents

    async def to_list(self, length=None):
        return self._documents


class Collection:
    def __init__(self, documents):
        self._documents = documents

    def find(self, query):
        return Cursor(self._documents)

    async def find_one(self, query):
        return None


class Request:
    def __init__(self):
        self.state = type("State", (), {})()
        self.headers = {"authorization": "Bearer opaque-idp-token"}


async def fetch_issuer(discovery_url):
    return ISSUER_BY_DISCOVERY_URL[discovery_url]


async def resolve(issuer, documents):
    idp_auth.unverified_issuer = lambda token: issuer
    idp_auth.fetch_issuer = fetch_issuer

    async def verify_idp_token(token, **kwargs):
        return NESTED_CLAIMS

    idp_auth.verify_idp_token = verify_idp_token
    try:
        return {"principal": await auth.resolve_principal(Request(), {"users": Collection(documents)})}
    except HTTPException as error:
        return {"status": error.status_code, "detail": error.detail}


async def main():
    print(json.dumps({
        "issuer_without_binding": await resolve("https://okta.test", []),
        "unknown_subject": await resolve("https://keycloak.test", []),
        "nested_identifier": await resolve("https://keycloak.test", [RECORD]),
    }))


asyncio.run(main())
'''


@pytest.fixture(scope="module")
def resolved_principals(tmp_path_factory):
    """Run the generated resolve_principal against a stubbed IdP and Mongo."""
    tmp_path = tmp_path_factory.mktemp("idp-behaviour")
    spec = tmp_path / "spec.yaml"
    spec.write_text(textwrap.dedent(_BEHAVIOUR_SPEC))
    output = tmp_path / "generated"
    FastAPIGenerator().generate(build_context(load_and_generate_ir(str(spec)).ir), output)
    result = subprocess.run(
        [sys.executable, "-c", _BEHAVIOUR_HARNESS],
        cwd=output,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestGeneratedPrincipalResolution:
    def test_issuer_without_binding_is_rejected(self, resolved_principals):
        """An IdP issuer no binding claims must never downgrade to anonymous."""
        assert resolved_principals["issuer_without_binding"] == {
            "status": 401,
            "detail": "Untrusted token issuer",
        }

    def test_unknown_subject_without_auto_provisioning_is_unauthorized(
        self, resolved_principals
    ):
        assert resolved_principals["unknown_subject"] == {
            "status": 401,
            "detail": "User not found and auto-provisioning is disabled",
        }

    def test_nested_identifier_claim_resolves_the_identity_record(
        self, resolved_principals
    ):
        principal = resolved_principals["nested_identifier"]["principal"]
        assert principal["sub"] == "user-1"
        assert principal["identity_collection"] == "users"
        assert principal["record"]["email"] == "nested@example.com"

    def test_nested_identifier_claim_is_not_treated_as_a_service_token(
        self, resolved_principals
    ):
        assert "is_service" not in resolved_principals["nested_identifier"]["principal"]
