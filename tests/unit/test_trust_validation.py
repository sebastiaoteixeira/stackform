from yaml_api_generator.parsers.transformers.trust_validation import (
    validate_spec_trust,
)


def _results(providers: dict):
    return validate_spec_trust({"providers": providers})


def _codes(providers: dict) -> set[str]:
    return {e.code for e in _results(providers)}


def _error_codes(providers: dict) -> set[str]:
    return {e.code for e in _results(providers) if e.severity == "error"}


def _warning_codes(providers: dict) -> set[str]:
    return {e.code for e in _results(providers) if e.severity == "warning"}


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


# ---- defaults ----

def test_app_trust_is_the_default_and_accepted():
    assert _error_codes({"keycloak": _oidc()}) == set()


def test_explicit_idp_trust_accepted():
    assert _error_codes({"keycloak": _idp()}) == set()


def test_idp_trust_without_audiences_produces_warning():
    config = {
        "type": "oidc",
        "client_id": "id",
        "trust": "idp",
        "discovery_url": "https://idp/.well-known/openid-configuration",
    }
    assert "TRUST_IDP_AUDIENCE_DEFAULTED" in _warning_codes({"keycloak": config})
    assert _error_codes({"keycloak": config}) == set()


def test_idp_trust_with_explicit_audiences_no_warning():
    assert "TRUST_IDP_AUDIENCE_DEFAULTED" not in _warning_codes(
        {"keycloak": _idp(audiences=["api://my-api"])}
    )
    assert _error_codes({"keycloak": _idp(audiences=["api://my-api"])}) == set()


def test_idp_trust_with_explicit_issuer_accepted():
    assert _error_codes({"keycloak": _idp(issuer="https://idp/")}) == set()


def test_idp_trust_audiences_tuple_reaches_ir_correctly():
    """Explicit audiences list suppresses TRUST_IDP_AUDIENCE_DEFAULTED warning."""
    assert "TRUST_IDP_AUDIENCE_DEFAULTED" not in _warning_codes(
        {"keycloak": _idp(audiences=["a", "b"])}
    )


# ---- TRUST_INVALID_VALUE ----

def test_unknown_trust_value_rejected():
    assert "TRUST_INVALID_VALUE" in _codes({"keycloak": _oidc(trust="external")})


# ---- TRUST_IDP_DISCOVERY_URL_REQUIRED (OIDC only) ----

def test_oidc_idp_without_discovery_url_rejected():
    config = {"type": "oidc", "client_id": "id", "trust": "idp"}
    assert "TRUST_IDP_DISCOVERY_URL_REQUIRED" in _codes({"keycloak": config})


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
