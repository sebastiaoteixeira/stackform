from yaml_api_generator.parsers.transformers.auth_validation import (
    validate_spec_auth,
)


def _codes(entities: dict, providers: dict | None = None) -> set[str]:
    spec = {"entities": entities, "providers": providers or {}}
    return {error.code for error in validate_spec_auth(spec)}


def _auth_entity(auth: dict, fields: dict | None = None) -> dict:
    return {
        "type": "auth",
        "auth": auth,
        "fields": fields if fields is not None else {"id": {"type": "id"}},
    }


# ---- AUTH_IDENTIFIER_REQUIRED ----

def test_password_without_identifier_rejected():
    entities = {"user": _auth_entity({"via": "password"})}
    assert "AUTH_IDENTIFIER_REQUIRED" in _codes(entities)


def test_apikey_without_identifier_rejected():
    entities = {"client": _auth_entity({"via": ["apiKey"]})}
    assert "AUTH_IDENTIFIER_REQUIRED" in _codes(entities)


def test_password_with_identifier_accepted():
    entities = {
        "user": _auth_entity(
            {"via": "password", "identifier": "email"},
            {"id": {"type": "id"}, "email": {"type": "string"}},
        )
    }
    assert _codes(entities) == set()


# ---- AUTH_IDENTIFIER_FIELD_NOT_FOUND ----

def test_identifier_unknown_field_rejected():
    entities = {"user": _auth_entity({"via": "password", "identifier": "ghost"})}
    assert "AUTH_IDENTIFIER_FIELD_NOT_FOUND" in _codes(entities)


def test_identifier_inherited_field_accepted():
    entities = {
        "base_user": {
            "abstract": True,
            "fields": {"id": {"type": "id"}, "email": {"type": "string"}},
        },
        "user": {
            "type": "auth",
            "extends": "base_user",
            "auth": {"via": "password", "identifier": "email"},
        },
    }
    assert _codes(entities) == set()


# ---- AUTH_API_KEY_FIELD_MISSING ----

def test_apikey_without_apikey_field_rejected():
    entities = {
        "client": _auth_entity(
            {"via": ["apiKey"], "identifier": "clientId"},
            {"id": {"type": "id"}, "clientId": {"type": "string"}},
        )
    }
    assert "AUTH_API_KEY_FIELD_MISSING" in _codes(entities)


def test_apikey_with_apikey_field_accepted():
    entities = {
        "client": _auth_entity(
            {"via": ["apiKey"], "identifier": "clientId"},
            {
                "id": {"type": "id"},
                "clientId": {"type": "string"},
                "apiKey": {"type": "string"},
            },
        )
    }
    assert _codes(entities) == set()


# ---- scope ----

def test_non_auth_entity_ignored():
    entities = {"article": {"fields": {"id": {"type": "id"}}}}
    assert _codes(entities) == set()


def test_oidc_only_via_needs_no_identifier():
    entities = {"user": _auth_entity({"via": ["oidc"]})}
    assert _codes(entities, {"oidc": {"type": "oidc"}}) == set()


# ---- AUTH_VIA_UNKNOWN_PROVIDER ----

def test_via_undeclared_provider_rejected():
    entities = {"user": _auth_entity({"via": ["keycloak"]})}
    assert _codes(entities) == {"AUTH_VIA_UNKNOWN_PROVIDER"}


def test_via_undeclared_provider_rejected_in_v01_collections():
    spec = {"collections": {"user": _auth_entity({"via": ["keycloak"], "identifier": "id"})}}
    errors = validate_spec_auth(spec, "collections")
    assert [(e.code, e.path) for e in errors] == [
        ("AUTH_VIA_UNKNOWN_PROVIDER", "collections.user.auth.via")
    ]
