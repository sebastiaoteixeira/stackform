import base64
import hashlib
import json
import os
import subprocess
import sys
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from jwt.algorithms import ECAlgorithm

from tests.conftest import VALID_DIR
from tests.unit.support.repositories import InMemoryRepository
from yaml_api_generator.runtime.dpop import (
    DPoPProofFactory,
    generate_private_key_pem,
    request_with_dpop,
)
from yaml_api_generator.generators.backend.builders.settings_builder import (
    build_settings_fields,
    generated_secret_values,
)
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


def _ir():
    return load_and_generate_ir(str(VALID_DIR / "auth-oidc-dpop.yaml")).ir


def _factory() -> DPoPProofFactory:
    return DPoPProofFactory.from_pem(generate_private_key_pem())


def _decode(proof: str) -> tuple[dict, dict]:
    header = jwt.get_unverified_header(proof)
    public_key = ECAlgorithm.from_jwk(json.dumps(header["jwk"]))
    claims = jwt.decode(proof, public_key, algorithms=["ES256"])
    return header, claims


def test_dpop_proof_is_signed_and_normalizes_target_uri():
    factory = _factory()
    token = "access-token"

    header, claims = _decode(
        factory.proof(
            "get",
            "HTTPS://API.Example.test:443/userinfo?include=roles#fragment",
            access_token=token,
        )
    )

    expected_ath = base64.urlsafe_b64encode(
        hashlib.sha256(token.encode()).digest()
    ).rstrip(b"=").decode()
    assert header["typ"] == "dpop+jwt"
    assert header["jwk"] == factory.public_jwk
    assert "d" not in header["jwk"]
    assert claims["htm"] == "GET"
    assert claims["htu"] == "https://api.example.test/userinfo"
    assert claims["ath"] == expected_ath
    assert claims["jti"]


@pytest.mark.asyncio
async def test_dpop_nonce_challenge_is_retried_once():
    class Response:
        def __init__(self, status_code, headers=None):
            self.status_code = status_code
            self.headers = headers or {}

    class Client:
        def __init__(self):
            self.calls = []
            self.responses = [
                Response(401, {"DPoP-Nonce": "server-nonce"}),
                Response(200),
            ]

        async def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return self.responses.pop(0)

    client = Client()
    response = await request_with_dpop(
        client,
        "POST",
        "https://idp.example.test/token",
        _factory(),
        data={"code": "code"},
    )

    assert response.status_code == 200
    assert len(client.calls) == 2
    _, first = _decode(client.calls[0][2]["headers"]["DPoP"])
    _, second = _decode(client.calls[1][2]["headers"]["DPoP"])
    assert "nonce" not in first
    assert second["nonce"] == "server-nonce"
    assert first["jti"] != second["jti"]


def test_generated_backend_uses_a_shared_persistent_key(tmp_path):
    ctx = build_context(_ir())
    fields = build_settings_fields(ctx)
    key_field = next(
        field for field in fields if field.env_name == "KEYCLOAK_DPOP_PRIVATE_KEY"
    )
    value = generated_secret_values(fields)[key_field.env_name]

    assert key_field.secret is True
    assert value.startswith('"') and value.endswith('"')
    DPoPProofFactory.from_pem(value[1:-1].replace("\\n", "\n"))

    FastAPIGenerator().generate(ctx, tmp_path)
    for source_path in tmp_path.rglob("*.py"):
        compile(source_path.read_text(), str(source_path), "exec")

    oidc_source = (tmp_path / "routes" / "oidc_routes.py").read_text()
    assert "settings.KEYCLOAK_DPOP_PRIVATE_KEY.get_secret_value()" in oidc_source
    assert "ec.generate_private_key" not in oidc_source

    command = [
        sys.executable,
        "-c",
        (
            "import json; from dependencies.dpop import DPoPProofFactory; "
            "from settings import settings; "
            "factory=DPoPProofFactory.from_pem("
            "settings.KEYCLOAK_DPOP_PRIVATE_KEY.get_secret_value()); "
            "print(json.dumps(factory.public_jwk, sort_keys=True))"
        ),
    ]
    first = subprocess.run(
        command,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    second = subprocess.run(
        command,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert first.stdout == second.stdout


def test_dpop_and_pkce_generate_together(tmp_path):
    spec = tmp_path / "combined.yaml"
    spec.write_text(
        (VALID_DIR / "auth-oidc-dpop.yaml")
        .read_text()
        .replace("    dpop: true", "    dpop: true\n    pkce: true")
    )
    output = tmp_path / "output"
    FastAPIGenerator().generate(
        build_context(load_and_generate_ir(str(spec)).ir),
        output,
    )

    for source_path in output.rglob("*.py"):
        compile(source_path.read_text(), str(source_path), "exec")
    oidc_source = (output / "routes" / "oidc_routes.py").read_text()
    assert "code_verifier" in oidc_source
    assert "request_with_dpop(" in oidc_source


@pytest.mark.parametrize("generator", [DRFGenerator(), RawASGIGenerator()])
def test_unsupported_backends_reject_dpop(generator, tmp_path):
    with pytest.raises(ConfigErrors) as raised:
        generator.generate(build_context(_ir()), tmp_path)

    assert [error.code for error in raised.value.errors] == [
        "BACKEND_FEATURE_UNSUPPORTED"
    ]


def test_dpop_is_rejected_for_idp_trust(tmp_path):
    source = (VALID_DIR / "auth-oidc-dpop.yaml").read_text()
    path = tmp_path / "idp-dpop.yaml"
    path.write_text(source.replace("dpop: true", "dpop: true\n    trust: idp"))

    with pytest.raises(ConfigErrors) as raised:
        load_and_generate_ir(str(path))

    assert "SCHEMA_VALIDATION_ERROR" in {
        error.code for error in raised.value.errors
    }


@pytest.mark.asyncio
async def test_runtime_oidc_sends_bound_proofs(monkeypatch):
    proof_factory = _factory()
    ir = _ir()
    runtime = build_runtime_context(ir)
    provider = ir.providers["keycloak"]
    collection = runtime.collections["users"]
    binding = runtime.auth.identity_collections["users"].bindings[0]
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    oidc._discovery_cache[DISCOVERY_URL] = DISCOVERY

    class Response:
        status_code = 200
        headers = {}

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class Client:
        calls = []
        responses = [
            Response({"access_token": "access", "token_type": "DPoP"}),
            Response({"sub": "subject", "email": "a@example.com"}),
        ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return self.responses.pop(0)

    monkeypatch.setattr(oidc.httpx, "AsyncClient", Client)
    await oidc.fetch_claims(provider, "code", "http://test/callback", dpop=proof_factory)

    token_headers = Client.calls[0][2]["headers"]
    userinfo_headers = Client.calls[1][2]["headers"]
    _, token_claims = _decode(token_headers["DPoP"])
    _, userinfo_claims = _decode(userinfo_headers["DPoP"])
    assert token_claims["htm"] == "POST"
    assert token_claims["htu"] == DISCOVERY["token_endpoint"]
    assert userinfo_headers["Authorization"] == "DPoP access"
    assert userinfo_claims["htu"] == DISCOVERY["userinfo_endpoint"]
    assert "ath" in userinfo_claims


def test_runtime_routes_require_configured_persistent_key(monkeypatch):
    runtime = build_runtime_context(_ir())
    repo = InMemoryRepository()
    repo.register_id_field("users", "id")
    registry = RepositoryRegistry.single(repo)
    monkeypatch.delenv("KEYCLOAK_DPOP_PRIVATE_KEY", raising=False)

    with pytest.raises(RuntimeError, match="KEYCLOAK_DPOP_PRIVATE_KEY is not set"):
        register_provider_routes(
            FastAPI(),
            runtime,
            registry,
            SessionTokens(runtime.session),
        )

    monkeypatch.setenv("KEYCLOAK_DPOP_PRIVATE_KEY", generate_private_key_pem())
    register_provider_routes(
        FastAPI(),
        runtime,
        registry,
        SessionTokens(runtime.session),
    )


@pytest.mark.asyncio
async def test_non_dpop_token_is_rejected_before_userinfo(monkeypatch):
    ir = _ir()
    runtime = build_runtime_context(ir)
    provider = ir.providers["keycloak"]
    collection = runtime.collections["users"]
    binding = runtime.auth.identity_collections["users"].bindings[0]
    exchange = AsyncMock(return_value={"access_token": "access", "token_type": "Bearer"})
    userinfo = AsyncMock()
    monkeypatch.setattr(oidc, "_exchange_code", exchange)
    monkeypatch.setattr(oidc, "_fetch_userinfo", userinfo)

    with pytest.raises(HTTPException) as raised:
        await oidc.fetch_claims(provider, "code", "http://test/callback", dpop=_factory())

    assert raised.value.status_code == 401
    assert raised.value.detail == "Provider did not issue a DPoP-bound token"
    userinfo.assert_not_awaited()
