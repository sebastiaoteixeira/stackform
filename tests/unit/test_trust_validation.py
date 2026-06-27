from yaml_api_generator.parsers.transformers.trust_validation import (
    validate_spec_trust,
)


def _codes(providers: dict) -> set[str]:
    return {error.code for error in validate_spec_trust({"providers": providers})}


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
        "issuer": "https://idp/",
        "audience": "my-app",
        **overrides,
    }


# ---- defaults ----

def test_app_trust_is_the_default_and_accepted():
    assert _codes({"keycloak": _oidc()}) == set()


def test_explicit_idp_trust_accepted():
    assert _codes({"keycloak": _idp()}) == set()


# ---- TRUST_INVALID_VALUE ----

def test_unknown_trust_value_rejected():
    assert "TRUST_INVALID_VALUE" in _codes({"keycloak": _oidc(trust="external")})


# ---- TRUST_IDP_ISSUER_REQUIRED / TRUST_IDP_AUDIENCE_REQUIRED ----

def test_idp_without_issuer_rejected():
    config = _idp()
    del config["issuer"]
    assert "TRUST_IDP_ISSUER_REQUIRED" in _codes({"keycloak": config})


def test_idp_without_audience_rejected():
    config = _idp()
    del config["audience"]
    assert "TRUST_IDP_AUDIENCE_REQUIRED" in _codes({"keycloak": config})


# ---- TRUST_IDP_PROVIDER_UNSUPPORTED ----

def test_idp_trust_on_non_idp_type_rejected():
    config = _idp(type="password")
    assert "TRUST_IDP_PROVIDER_UNSUPPORTED" in _codes({"local": config})


# ---- TRUST_IDP_APP_FIELD_FORBIDDEN ----

def test_idp_with_app_signing_field_rejected():
    assert "TRUST_IDP_APP_FIELD_FORBIDDEN" in _codes({"keycloak": _idp(secret="x")})


# ---- TRUST_APP_FIELD_FORBIDDEN ----

def test_app_trust_with_issuer_rejected():
    assert "TRUST_APP_FIELD_FORBIDDEN" in _codes({"keycloak": _oidc(issuer="https://idp/")})


# ---- scope ----

def test_no_providers_block_is_clean():
    assert validate_spec_trust({}) == []
