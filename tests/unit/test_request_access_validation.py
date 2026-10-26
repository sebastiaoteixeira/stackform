import pytest

from yaml_api_generator.parsers.transformers.access_validation import (
    validate_spec_access,
)
from yaml_api_generator.parsers.transformers.dto_validation import validate_spec_dtos
from yaml_api_generator.parsers.transformers.request_path_validation import (
    validate_spec_request_paths,
)


_ENTITIES = {
    "user": {
        "type": "auth",
        "auth": {"identifier": "email", "via": "password", "roles": "role"},
        "fields": {
            "id": {"type": "id"},
            "role": {"type": "enum", "values": ["admin", "user"]},
        },
    },
    "membership": {"fields": {"id": {"type": "id"}, "role": {"type": "string"}}},
}

_DTO = {"createMembership": {"fields": {"role": {"type": "string"}}}}


def _access_codes(access, op_name="create", dto=None) -> set[str]:
    spec = {
        "entities": _ENTITIES,
        "dto": dto if dto is not None else _DTO,
        "controllers": {
            "c": {"operations": {op_name: {"access": access}}},
        },
    }
    return {error.code for error in validate_spec_access(spec)}


# ---- REQUEST_TYPE_NOT_FOUND ----

def test_request_type_not_found():
    access = [{"given": {"x": "request:NoSuchType"},
              "when": "x.role equals 'admin'"}]
    assert "REQUEST_TYPE_NOT_FOUND" in _access_codes(access)


def test_request_type_dto_resolves():
    access = [{"given": {"x": "request:createMembership"},
              "when": "x.role equals 'admin'"}]
    assert _access_codes(access) == set()


def test_request_type_entity_resolves():
    access = [{"given": {"x": "request:membership"},
              "when": "x.role equals 'admin'"}]
    assert _access_codes(access) == set()


def test_request_type_primitive_resolves():
    access = [{"given": {"x": "request.path:string"},
              "when": "x.orgId equals 'a'"}]
    assert _access_codes(access, op_name="get") == set()


# ---- REQUEST_TYPE_ON_LEAF ----

def test_request_type_on_leaf_header():
    access = [{"given": {"x": "request.header:createMembership"},
              "when": "x.authorization equals 'a'"}]
    assert "REQUEST_TYPE_ON_LEAF" in _access_codes(access, op_name="get")


# ---- REQUEST_BODY_ON_BODILESS_OP ----

def test_request_body_on_get_rejected():
    access = [{"given": {"x": "request.body"},
              "when": "x.role equals 'admin'"}]
    assert "REQUEST_BODY_ON_BODILESS_OP" in _access_codes(access, op_name="get")


def test_whole_request_on_delete_rejected():
    access = [{"given": {"x": "request"},
              "when": "x.body equals 'admin'"}]
    assert "REQUEST_BODY_ON_BODILESS_OP" in _access_codes(access, op_name="delete")


def test_request_query_on_get_allowed():
    access = [{"given": {"x": "request.query"},
              "when": "x.page equals '1'"}]
    assert _access_codes(access, op_name="get") == set()


# ---- create rule referencing a request symbol stays VALID ----

def test_request_referencing_create_rule_valid():
    access = [{"given": {"caller": "identity:user", "payload": "request:createMembership"},
              "when": "caller.role equals 'admin'"}]
    assert _access_codes(access, op_name="create") == set()


# ---- DTO fields ----

def _dto_codes(dto) -> set[str]:
    return {e.code for e in validate_spec_dtos({"entities": _ENTITIES, "dto": dto})}


def test_dto_clean_fields_valid():
    dto = {"d": {"fields": {"x": {"type": "string", "required": True, "format": "email"}}}}
    assert _dto_codes(dto) == set()


# ---- DTO_NOT_FOUND ----

def test_dto_ref_to_undeclared_type():
    dto = {"d": {"fields": {"x": {"type": "ref", "ref": "ghost"}}}}
    assert "DTO_NOT_FOUND" in _dto_codes(dto)


def test_dto_ref_to_entity_resolves():
    dto = {"d": {"fields": {"x": {"type": "ref", "ref": "membership"}}}}
    assert _dto_codes(dto) == set()


# ---- REQUEST_PATH_PARAM_NOT_DECLARED (post-desugar route) ----

def _request_path_codes(route_path, when, binding="request") -> set[str]:
    spec = {
        "controllers": {
            "c": {
                "base_path": "",
                "routes": {
                    "r": {
                        "path": route_path,
                        "access": [
                            {"given": {"req": binding}, "when": when}
                        ],
                    }
                },
            }
        }
    }
    return {e.code for e in validate_spec_request_paths(spec)}


def test_request_path_param_not_declared():
    codes = _request_path_codes("/orgs/{orgId}", "req.path.missing equals 'a'")
    assert "REQUEST_PATH_PARAM_NOT_DECLARED" in codes


def test_request_path_param_declared_valid():
    codes = _request_path_codes("/orgs/{orgId}", "req.path.orgId equals 'a'")
    assert codes == set()


@pytest.mark.parametrize(
    ("binding", "when", "codes"),
    [
        ("request:createMembership", "req.path.missing equals 'a'", {"REQUEST_PATH_PARAM_NOT_DECLARED"}),
        ("request.path", "req.missing is null", {"REQUEST_PATH_PARAM_NOT_DECLARED"}),
        ("request.path", "req.orgId equals 'a'", set()),
        ("request.body", "req.missing equals 'a'", set()),
    ],
    ids=["typed-request", "path-part", "path-part-declared", "body-part"],
)
def test_request_path_params_resolve_through_every_binding(binding, when, codes):
    assert _request_path_codes("/orgs/{orgId}", when, binding) == codes


def test_dto_nested_ref_to_undeclared_type():
    dto = {"d": {"fields": {"x": {"type": "array", "items": {"type": "ref", "ref": "ghost"}}}}}
    assert "DTO_NOT_FOUND" in _dto_codes(dto)
