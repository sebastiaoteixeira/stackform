from yaml_api_generator.parsers.transformers.access_validation import (
    validate_spec_access,
)


_ENTITIES = {
    "user": {
        "type": "auth",
        "auth": {"identifier": "email", "via": "password"},
        "roles": {"values": ["admin", "editor"], "default": "editor"},
        "fields": {"id": {"type": "id"}},
    },
    "article": {
        "fields": {"id": {"type": "id"}, "author_id": {"type": "string"}},
    },
}


def _codes(controllers: dict, entities: dict | None = None) -> set[str]:
    spec = {"entities": entities or _ENTITIES, "controllers": controllers}
    return {error.code for error in validate_spec_access(spec)}


def _ownership_rule(when: str = "principal.sub equals document.author_id") -> dict:
    return {
        "given": {"principal": "identity:user", "document": "articles"},
        "when": when,
    }


# ---- WHEN_UNBOUND_SYMBOL ----

def test_unbound_symbol_in_when_rejected():
    controllers = {"c": {"operations": {"get": {"access": [
        _ownership_rule("ghost.sub equals document.author_id")
    ]}}}}
    assert "WHEN_UNBOUND_SYMBOL" in _codes(controllers)


def test_given_bound_symbol_accepted():
    controllers = {"c": {"operations": {"update": {"access": [{
        "given": {"xx": "identity:user", "document": "articles"},
        "when": "xx.sub equals document.author_id",
    }]}}}}
    assert _codes(controllers) == set()


def test_builtin_principal_document_roots_accepted():
    controllers = {"c": {"operations": {"get": {"access": [_ownership_rule()]}}}}
    assert _codes(controllers) == set()


# ---- ACCESS_RULE_INVALID: undeclared roles ----

def test_scoped_role_not_in_values_rejected():
    controllers = {"c": {"operations": {"list": {"access": "user:superuser"}}}}
    assert "ACCESS_RULE_INVALID" in _codes(controllers)


def test_scoped_role_in_values_accepted():
    controllers = {"c": {"operations": {"list": {"access": "user:admin"}}}}
    assert _codes(controllers) == set()


def test_unscoped_role_not_in_values_rejected():
    controllers = {"c": {"operations": {"list": {"access": "superuser"}}}}
    assert "ACCESS_RULE_INVALID" in _codes(controllers)


def test_role_wildcard_accepted():
    controllers = {"c": {"operations": {"list": {"access": "user:*"}}}}
    assert _codes(controllers) == set()


# ---- ACCESS_RULE_INVALID: document-dependent when on create ----

def test_document_when_on_create_rejected():
    controllers = {"c": {"operations": {"create": {"access": [_ownership_rule()]}}}}
    assert "ACCESS_RULE_INVALID" in _codes(controllers)


def test_document_when_on_register_rejected():
    controllers = {"c": {"operations": {"register": {"access": [_ownership_rule()]}}}}
    assert "ACCESS_RULE_INVALID" in _codes(controllers)


def test_non_document_when_on_create_accepted():
    controllers = {"c": {"operations": {"create": {"access": [{
        "given": {"principal": "identity:user"},
        "when": "principal.role equals 'admin'",
    }]}}}}
    assert _codes(controllers) == set()


# ---- ACCESS_RULE_INVALID: empty access list ----

def test_empty_access_list_rejected():
    controllers = {"c": {"operations": {"list": {"access": []}}}}
    assert "ACCESS_RULE_INVALID" in _codes(controllers)


# ---- ACCESS_RULE_INVALID: contradictory effects ----

def test_contradictory_allow_deny_rejected():
    rule = {"given": {"principal": "identity:user"},
            "when": "principal.role equals 'admin'"}
    controllers = {"c": {"operations": {"get": {"access": [
        {**rule, "then": "allow"},
        {**rule, "then": "deny"},
    ]}}}}
    assert "ACCESS_RULE_INVALID" in _codes(controllers)


def test_same_effect_duplicate_accepted():
    rule = {"given": {"principal": "identity:user"},
            "when": "principal.role equals 'admin'", "then": "allow"}
    controllers = {"c": {"operations": {"get": {"access": [rule, dict(rule)]}}}}
    assert _codes(controllers) == set()
