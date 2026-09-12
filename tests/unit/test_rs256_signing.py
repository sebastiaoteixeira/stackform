"""RS256 session-token signing, JWKS exposure, and HS256 default preservation.

The generated backends are exercised by running the code they emit: a token is
minted through the generated module, the JWKS is served by the generated route,
and the signature is verified against the published key.
"""

import compileall
import hashlib
import hmac
import json
import os
import subprocess
import sys
import textwrap
from base64 import urlsafe_b64encode
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from tests.conftest import VALID_DIR
from tests.unit.support.repositories import InMemoryRepository
from yaml_api_generator.generators.backend.builders.settings_builder import (
    build_settings_fields,
    generated_secret_values,
)
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.server.asgi.runner import ASGIApp
from yaml_api_generator.server.common.auth.jwt import (
    JWKS_PATH,
    AsymmetricSessionTokens,
    SymmetricSessionTokens,
    build_session_tokens,
)
from yaml_api_generator.server.common.context_builder import build_runtime_context
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.common.server_context import RuntimeSessionConfig
from yaml_api_generator.server.fastapi.factory import register_fastapi_routes
from yaml_api_generator.utils.rsa_keys import generate_private_key_pem, public_key_pem

PRIVATE_COMPONENTS = {"d", "p", "q", "dp", "dq", "qi", "oth"}


def _ir(name: str):
    return load_and_generate_ir(str(VALID_DIR / name)).ir


def _ctx(name: str):
    return build_context(_ir(name))


def _spec_with_session(tmp_path: Path, fixture: str, algorithm: str) -> str:
    spec = tmp_path / f"{Path(fixture).stem}-{algorithm}.yaml"
    spec.write_text(
        (VALID_DIR / fixture).read_text() + f"session:\n  algorithm: {algorithm}\n"
    )
    return str(spec)


@pytest.fixture
def hs_ctx():
    return _ctx("auth-password.yaml")


@pytest.fixture
def rs_ctx():
    return _ctx("auth-password-rs256.yaml")


@pytest.fixture(scope="module")
def signing_pem() -> str:
    return generate_private_key_pem()


@pytest.fixture(scope="module")
def retired_pem() -> str:
    return generate_private_key_pem()


class TestSessionParsing:
    def test_default_algorithm_is_hs256(self):
        assert _ir("auth-password.yaml").session.algorithm == "HS256"

    def test_rs256_algorithm_parsed(self):
        assert _ir("auth-password-rs256.yaml").session.algorithm == "RS256"

    def test_algorithm_flows_into_compile_context(self, rs_ctx):
        assert rs_ctx.session.algorithm == "RS256"
        assert rs_ctx.session.uses_asymmetric is True

    def test_invalid_algorithm_rejected(self, tmp_path):
        with pytest.raises(ConfigErrors):
            load_and_generate_ir(
                _spec_with_session(tmp_path, "auth-password.yaml", "BADALG")
            )


class TestSettings:
    def test_hs256_uses_shared_secret(self, hs_ctx):
        names = {f.env_name for f in build_settings_fields(hs_ctx)}
        assert "JWT_SECRET" in names
        assert "JWT_PRIVATE_KEY" not in names

    def test_rs256_uses_private_key_and_retirement_slot(self, rs_ctx):
        names = {f.env_name for f in build_settings_fields(rs_ctx)}
        assert {"JWT_PRIVATE_KEY", "JWT_RETIRED_PUBLIC_KEY"} <= names
        assert "JWT_SECRET" not in names

    def test_private_key_is_required_and_marked_secret(self, rs_ctx):
        field = next(
            f for f in build_settings_fields(rs_ctx) if f.env_name == "JWT_PRIVATE_KEY"
        )
        assert field.default is None
        assert field.secret is True

    def test_generated_private_key_is_a_quoted_pem(self, rs_ctx):
        fields = build_settings_fields(rs_ctx)
        value = generated_secret_values(fields)["JWT_PRIVATE_KEY"]
        assert value.startswith('"') and value.endswith('"')
        assert "BEGIN PRIVATE KEY" in value[1:-1].replace("\\n", "\n")


class TestCapabilityValidation:
    @pytest.mark.parametrize(
        "generator", [FastAPIGenerator(), DRFGenerator(), RawASGIGenerator()]
    )
    def test_rs256_without_session_tokens_is_rejected(self, generator, tmp_path):
        ctx = build_context(
            load_and_generate_ir(
                _spec_with_session(tmp_path, "basic-crud.yaml", "RS256")
            ).ir
        )
        with pytest.raises(ConfigErrors) as excinfo:
            generator.generate(ctx, tmp_path / "out")
        assert excinfo.value.errors[0].code == "SESSION_ALGORITHM_UNUSED"

    def test_idp_only_spec_cannot_ask_for_rs256(self, tmp_path):
        ctx = build_context(
            load_and_generate_ir(
                _spec_with_session(tmp_path, "auth-oidc-idp.yaml", "RS256")
            ).ir
        )
        with pytest.raises(ConfigErrors) as excinfo:
            FastAPIGenerator().generate(ctx, tmp_path / "out")
        assert excinfo.value.errors[0].code == "SESSION_ALGORITHM_UNUSED"

    def test_app_trust_and_idp_trust_compose(self, tmp_path):
        ctx = build_context(
            load_and_generate_ir(
                _spec_with_session(tmp_path, "auth-dual-trust.yaml", "RS256")
            ).ir
        )
        output = tmp_path / "dual"
        FastAPIGenerator().generate(ctx, output)
        assert (output / "routes" / "jwks.py").exists()
        assert (output / "dependencies" / "idp_auth.py").exists()


def _generate(generator, fixture_ctx, output: Path) -> Path:
    generator.generate(fixture_ctx, output)
    assert compileall.compile_dir(str(output), quiet=1)
    return output


def _run(output: Path, body: str, **env: str) -> dict:
    script = textwrap.dedent(
        f"""
        import json
        import sys

        sys.path.insert(0, {str(output)!r})
        """
    ) + textwrap.dedent(body)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(output),
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


_FASTAPI_ROUND_TRIP = """
from fastapi.testclient import TestClient

import app
from dependencies.jwt_utils import create_jwt_token, decode_jwt_token

token = create_jwt_token("user-1", "user")
response = TestClient(app.app).get("/.well-known/jwks.json")
print(json.dumps({
    "status": response.status_code,
    "jwks": response.json(),
    "token": token,
    "decoded": decode_jwt_token(token),
}))
"""

_RAW_ROUND_TRIP = """
import asyncio

import app
from dependencies.jwt_utils import create_jwt_token, decode_jwt_token

handler, params = app.ASGIApp._match_route("GET", "/.well-known/jwks.json")
status, payload = asyncio.run(handler(params, None, {}, None))
token = create_jwt_token("user-1", "user")
print(json.dumps({
    "status": status,
    "jwks": payload,
    "token": token,
    "decoded": decode_jwt_token(token),
}))
"""

_DRF_ROUND_TRIP = """
import importlib.util

spec = importlib.util.spec_from_file_location(
    "drf_jwt_utils", "api/authentication/jwt_utils.py"
)
jwt_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jwt_utils)

token = jwt_utils.create_jwt_token("user-1", "user")
print(json.dumps({
    "status": 200,
    "jwks": jwt_utils.public_jwks(),
    "token": token,
    "decoded": jwt_utils.decode_jwt_token(token),
}))
"""

_BACKENDS = {
    "fastapi": (FastAPIGenerator(), _FASTAPI_ROUND_TRIP),
    "drf": (DRFGenerator(), _DRF_ROUND_TRIP),
    "raw": (RawASGIGenerator(), _RAW_ROUND_TRIP),
}


@pytest.fixture(params=sorted(_BACKENDS))
def round_trip(request, rs_ctx, tmp_path, signing_pem):
    generator, body = _BACKENDS[request.param]
    output = _generate(generator, rs_ctx, tmp_path / request.param)
    return _run(
        output, body, JWT_PRIVATE_KEY=signing_pem, DJANGO_SECRET_KEY="test-secret"
    )


class TestGeneratedBackends:
    def test_jwks_is_served_and_verifies_the_minted_token(self, round_trip):
        assert round_trip["status"] == 200
        published = round_trip["jwks"]["keys"][0]
        header = pyjwt.get_unverified_header(round_trip["token"])
        assert header["alg"] == "RS256"
        assert header["kid"] == published["kid"]
        claims = pyjwt.decode(
            round_trip["token"],
            pyjwt.PyJWK.from_dict(published).key,
            algorithms=["RS256"],
        )
        assert claims["sub"] == "user-1"
        assert claims["identity_collection"] == "user"

    def test_generated_decoder_accepts_its_own_token(self, round_trip):
        assert round_trip["decoded"]["sub"] == "user-1"

    def test_jwks_never_exposes_private_material(self, round_trip):
        for published in round_trip["jwks"]["keys"]:
            assert not PRIVATE_COMPONENTS & set(published)
            assert published["use"] == "sig"
            assert published["alg"] == "RS256"
        assert "PRIVATE KEY" not in json.dumps(round_trip["jwks"])

    def test_every_backend_publishes_the_same_key(self, round_trip, signing_pem):
        published = round_trip["jwks"]["keys"][0]
        expected = AsymmetricSessionTokens(signing_pem).public_jwks()["keys"][0]
        assert published["n"] == expected["n"]
        assert published["kid"] == expected["kid"]


class TestKeyRotation:
    @pytest.fixture
    def rotated(self, rs_ctx, tmp_path, signing_pem, retired_pem):
        output = _generate(FastAPIGenerator(), rs_ctx, tmp_path / "rotated")
        return _run(
            output,
            _FASTAPI_ROUND_TRIP,
            JWT_PRIVATE_KEY=signing_pem,
            JWT_RETIRED_PUBLIC_KEY=public_key_pem(retired_pem),
        )

    def test_retired_key_is_still_published(self, rotated, signing_pem, retired_pem):
        published = {entry["kid"] for entry in rotated["jwks"]["keys"]}
        signing = AsymmetricSessionTokens(signing_pem).public_jwks()["keys"][0]["kid"]
        retired = AsymmetricSessionTokens(retired_pem).public_jwks()["keys"][0]["kid"]
        assert published == {signing, retired}

    def test_new_tokens_carry_the_current_kid(self, rotated, signing_pem):
        signing = AsymmetricSessionTokens(signing_pem).public_jwks()["keys"][0]["kid"]
        assert pyjwt.get_unverified_header(rotated["token"])["kid"] == signing

    def test_tokens_from_the_retired_key_survive_until_expiry(
        self, rs_ctx, tmp_path, signing_pem, retired_pem
    ):
        output = _generate(FastAPIGenerator(), rs_ctx, tmp_path / "drain")
        minted = _run(output, _FASTAPI_ROUND_TRIP, JWT_PRIVATE_KEY=retired_pem)
        accepted = _run(
            output,
            f"""
from dependencies.jwt_utils import decode_jwt_token

print(json.dumps({{"claims": decode_jwt_token({minted["token"]!r})}}))
""",
            JWT_PRIVATE_KEY=signing_pem,
            JWT_RETIRED_PUBLIC_KEY=public_key_pem(retired_pem),
        )
        assert accepted["claims"]["sub"] == "user-1"

    def test_tokens_from_an_unpublished_key_are_refused(
        self, rs_ctx, tmp_path, signing_pem, retired_pem
    ):
        output = _generate(FastAPIGenerator(), rs_ctx, tmp_path / "unpublished")
        minted = _run(output, _FASTAPI_ROUND_TRIP, JWT_PRIVATE_KEY=retired_pem)
        refused = _run(
            output,
            f"""
from dependencies.jwt_utils import decode_jwt_token

print(json.dumps({{"claims": decode_jwt_token({minted["token"]!r})}}))
""",
            JWT_PRIVATE_KEY=signing_pem,
        )
        assert refused["claims"] is None


def _b64(payload: dict) -> bytes:
    return urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")


def _hs256_forgery(signing_pem: str, algorithm: str) -> str:
    """A token that claims the published RSA key as an HMAC secret."""
    published = AsymmetricSessionTokens(signing_pem).public_jwks()["keys"][0]
    secret = public_key_pem(signing_pem).encode()
    header = _b64({"alg": algorithm, "typ": "JWT", "kid": published["kid"]})
    claims = _b64({"sub": "attacker", "identity_collection": "users"})
    signed = b".".join((header, claims))
    signature = hmac.new(secret, signed, hashlib.sha256).digest()
    return b".".join((signed, urlsafe_b64encode(signature).rstrip(b"="))).decode()


class TestAlgorithmPinning:
    def _refuses(self, output: Path, token: str, signing_pem: str) -> None:
        refused = _run(
            output,
            f"""
from dependencies.jwt_utils import decode_jwt_token

print(json.dumps({{"claims": decode_jwt_token({token!r})}}))
""",
            JWT_PRIVATE_KEY=signing_pem,
        )
        assert refused["claims"] is None

    def test_hs256_forgery_signed_with_the_published_key_is_refused(
        self, rs_ctx, tmp_path, signing_pem
    ):
        output = _generate(FastAPIGenerator(), rs_ctx, tmp_path / "pinned")
        self._refuses(output, _hs256_forgery(signing_pem, "HS256"), signing_pem)

    def test_algorithm_header_cannot_smuggle_a_weaker_choice(
        self, rs_ctx, tmp_path, signing_pem
    ):
        output = _generate(FastAPIGenerator(), rs_ctx, tmp_path / "smuggled")
        self._refuses(output, _hs256_forgery(signing_pem, "RS256"), signing_pem)

    def test_unsigned_token_is_refused(self, rs_ctx, tmp_path, signing_pem):
        output = _generate(FastAPIGenerator(), rs_ctx, tmp_path / "unsigned")
        forged = pyjwt.encode(
            {"sub": "attacker", "identity_collection": "users"}, None, algorithm="none"
        )
        self._refuses(output, forged, signing_pem)

    def test_a_token_without_a_kid_is_refused(self, rs_ctx, tmp_path, signing_pem):
        output = _generate(FastAPIGenerator(), rs_ctx, tmp_path / "kidless")
        forged = pyjwt.encode(
            {"sub": "attacker", "identity_collection": "users"},
            signing_pem,
            algorithm="RS256",
            headers={},
        )
        self._refuses(output, forged, signing_pem)


class TestHS256Unchanged:
    @pytest.mark.parametrize("backend", sorted(_BACKENDS))
    def test_no_jwks_artifact_is_emitted(self, backend, hs_ctx, tmp_path):
        generator, _ = _BACKENDS[backend]
        output = _generate(generator, hs_ctx, tmp_path / backend)
        assert not list(output.rglob("jwks*.py"))

    def test_tokens_are_still_hs256_and_carry_no_kid(self, hs_ctx, tmp_path):
        output = _generate(FastAPIGenerator(), hs_ctx, tmp_path / "hs")
        minted = _run(
            output,
            """
from dependencies.jwt_utils import create_jwt_token, decode_jwt_token

token = create_jwt_token("user-1", "user")
print(json.dumps({"token": token, "decoded": decode_jwt_token(token)}))
""",
            JWT_SECRET="test-secret-at-least-thirty-two-bytes",
        )
        header = pyjwt.get_unverified_header(minted["token"])
        assert header["alg"] == "HS256"
        assert "kid" not in header
        assert minted["decoded"]["sub"] == "user-1"

    def test_crypto_extra_is_required_only_for_rs256(self, hs_ctx, rs_ctx, tmp_path):
        hs = _generate(RawASGIGenerator(), hs_ctx, tmp_path / "hs")
        rs = _generate(RawASGIGenerator(), rs_ctx, tmp_path / "rs")
        assert "pyjwt\n" in (hs / "requirements.txt").read_text()
        assert "pyjwt[crypto]" in (rs / "requirements.txt").read_text()


def _dev_context(fixture: str):
    return build_runtime_context(_ir(fixture))


def _dev_registry(documents: dict | None = None) -> RepositoryRegistry:
    repository = InMemoryRepository(documents or {})
    repository.register_id_field("users", "id")
    return RepositoryRegistry.single(repository)


class TestDevServerTokens:
    def test_symmetric_is_the_default(self):
        tokens = build_session_tokens(RuntimeSessionConfig())
        assert isinstance(tokens, SymmetricSessionTokens)
        assert tokens.algorithm == "HS256"
        assert tokens.public_jwks() == {"keys": []}

    def test_asymmetric_uses_the_configured_key(self, monkeypatch, signing_pem):
        monkeypatch.setenv("JWT_PRIVATE_KEY", signing_pem)
        tokens = build_session_tokens(RuntimeSessionConfig(algorithm="RS256"))
        token = tokens.create("user-1", "user")
        published = tokens.public_jwks()["keys"][0]
        assert pyjwt.get_unverified_header(token)["kid"] == published["kid"]
        claims = pyjwt.decode(
            token, pyjwt.PyJWK.from_dict(published).key, algorithms=["RS256"]
        )
        assert claims["sub"] == "user-1"

    def test_escaped_newlines_in_the_environment_are_restored(
        self, monkeypatch, signing_pem
    ):
        monkeypatch.setenv("JWT_PRIVATE_KEY", signing_pem.replace("\n", "\\n"))
        tokens = build_session_tokens(RuntimeSessionConfig(algorithm="RS256"))
        expected = AsymmetricSessionTokens(signing_pem).public_jwks()["keys"][0]
        assert tokens.public_jwks()["keys"][0]["kid"] == expected["kid"]

    def test_an_ephemeral_key_is_used_when_none_is_configured(self, monkeypatch, caplog):
        monkeypatch.delenv("JWT_PRIVATE_KEY", raising=False)
        tokens = build_session_tokens(RuntimeSessionConfig(algorithm="RS256"))
        assert tokens.public_jwks()["keys"]
        assert "ephemeral key" in caplog.text

    def test_decoding_never_leaks_internal_errors(self, signing_pem):
        tokens = AsymmetricSessionTokens(signing_pem)
        assert tokens.decode("not-a-token") is None
        assert tokens.decode(pyjwt.encode({"sub": "x"}, "secret")) is None


class TestDevServerRoutes:
    def test_jwks_route_is_mounted_only_for_rs256(self):
        rs = [route.path for route in _dev_context("auth-password-rs256.yaml").routes]
        hs = [route.path for route in _dev_context("auth-password.yaml").routes]
        assert JWKS_PATH in rs
        assert JWKS_PATH not in hs

    def test_fastapi_dev_server_publishes_the_signing_key(self, monkeypatch, signing_pem):
        from fastapi import FastAPI

        monkeypatch.setenv("JWT_PRIVATE_KEY", signing_pem)
        ctx = _dev_context("auth-password-rs256.yaml")
        app = FastAPI()
        register_fastapi_routes(app, ctx, _dev_registry())

        response = TestClient(app).get(JWKS_PATH)
        assert response.status_code == 200
        published = response.json()["keys"][0]
        assert not PRIVATE_COMPONENTS & set(published)
        assert published["kid"] == (
            AsymmetricSessionTokens(signing_pem).public_jwks()["keys"][0]["kid"]
        )

    @pytest.mark.asyncio
    async def test_raw_dev_server_serves_the_jwks(self, monkeypatch, signing_pem):
        monkeypatch.setenv("JWT_PRIVATE_KEY", signing_pem)
        ctx = _dev_context("auth-password-rs256.yaml")
        app = ASGIApp(ctx, _dev_registry())
        sent: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await app(
            {"type": "http", "method": "GET", "path": JWKS_PATH, "headers": []},
            receive,
            send,
        )
        assert sent[0]["status"] == 200
        published = json.loads(sent[1]["body"])["keys"][0]
        assert not PRIVATE_COMPONENTS & set(published)

    @pytest.mark.asyncio
    async def test_login_token_verifies_against_the_published_jwks(
        self, monkeypatch, signing_pem
    ):
        from yaml_api_generator.server.common.auth.password import hash_password
        from yaml_api_generator.server.common.pipeline_builder import PipelineBuilder

        monkeypatch.setenv("JWT_PRIVATE_KEY", signing_pem)
        ctx = _dev_context("auth-password-rs256.yaml")
        registry = _dev_registry(
            {
                "users": [
                    {
                        "id": "user-1",
                        "email": "a@b.com",
                        "name": "Test",
                        "_auth": {"passwordHash": hash_password("secret123")},
                    }
                ]
            }
        )
        builder = PipelineBuilder(ctx=ctx, registry=registry)

        def pipeline_for(operation: str):
            route = next(r for r in ctx.routes if r.operation == operation)
            return builder.build_for_route(route)

        logged_in = await pipeline_for("login").run(
            headers={},
            url_params={},
            body={"email": "a@b.com", "password": "secret123"},
        )
        served = await pipeline_for("jwks").run(headers={}, url_params={}, body=None)

        token = logged_in.response["token"]
        published = served.response["keys"][0]
        assert pyjwt.get_unverified_header(token)["kid"] == published["kid"]
        claims = pyjwt.decode(
            token, pyjwt.PyJWK.from_dict(published).key, algorithms=["RS256"]
        )
        assert claims["sub"] == "user-1"
