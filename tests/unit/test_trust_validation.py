import pytest
from jsonschema import Draft202012Validator

from yaml_api_generator.parsers.transformers.trust_validation import validate_spec_trust
from yaml_api_generator.parsers.yaml_parser import SCHEMA_REGISTRY


def _warning_codes(providers: dict) -> set[str]:
    return {e.code for e in validate_spec_trust({"providers": providers})}


def _schema_errors(version: str, provider: dict) -> list[str]:
    validator = Draft202012Validator(
        {"$ref": f"yaml-spec-v{version}.schema.json#/$defs/ProviderConfig"},
        registry=SCHEMA_REGISTRY,
    )
    return [error.message for error in validator.iter_errors(provider)]


def _oidc(**overrides) -> dict:
    return {
        "type": "oidc",
        "client_id": "id",
        "client_secret": "secret",
        "discovery_url": "https://idp/.well-known/openid-configuration",
        **overrides,
    }


def _idp(**overrides) -> dict:
    return {
        "type": "oidc",
        "client_id": "id",
        "trust": "idp",
        "discovery_url": "https://idp/.well-known/openid-configuration",
        **overrides,
    }


VERSIONS = ["0.2", "0.3"]

ACCEPTED = {
    "app-default": _oidc(),
    "idp": _idp(),
    "idp-audiences": _idp(audiences=["api://my-api"]),
    "idp-issuer": _idp(issuer="https://idp/"),
}

REJECTED = {
    "unknown-trust": _oidc(trust="external"),
    "idp-without-discovery-url": {"type": "oidc", "client_id": "id", "trust": "idp"},
    "idp-on-password-type": _idp(type="password"),
    "idp-with-app-signing-field": _idp(secret="x"),
    "app-with-issuer": _oidc(issuer="https://idp/"),
}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("provider", ACCEPTED.values(), ids=list(ACCEPTED))
def test_schema_accepts_coherent_trust(version, provider):
    assert _schema_errors(version, provider) == []


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("provider", REJECTED.values(), ids=list(REJECTED))
def test_schema_rejects_incoherent_trust(version, provider):
    assert _schema_errors(version, provider) != []


@pytest.mark.parametrize("key", ["pkce", "dpop"])
def test_v03_schema_rejects_app_only_flags_under_idp_trust(key):
    assert _schema_errors("0.3", _idp(**{key: True})) != []
    assert _schema_errors("0.3", _oidc(**{key: True})) == []


def test_idp_trust_without_audiences_produces_warning():
    assert _warning_codes({"keycloak": _idp()}) == {"TRUST_IDP_AUDIENCE_DEFAULTED"}


def test_idp_trust_with_explicit_audiences_no_warning():
    assert _warning_codes({"keycloak": _idp(audiences=["a", "b"])}) == set()


def test_app_trust_produces_no_warning():
    assert _warning_codes({"keycloak": _oidc()}) == set()


def test_no_providers_block_is_clean():
    assert validate_spec_trust({}) == []
