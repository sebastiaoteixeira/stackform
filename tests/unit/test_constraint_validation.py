import pytest

from yaml_api_generator.parsers.transformers.constraint_validation import (
    validate_spec_constraints,
)
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


def _spec(field: dict) -> dict:
    return {"entities": {"post": {"fields": {"value": field}}}}


def _codes(field: dict) -> set[str]:
    return {e.code for e in validate_spec_constraints(_spec(field))}


def _errors(field: dict) -> list:
    return validate_spec_constraints(_spec(field))


# ---- Invalid constraints ----

def test_number_min_greater_than_max_rejected():
    assert "FIELD_CONSTRAINT_INVALID" in _codes({"type": "number", "min": 10, "max": 1})


def test_string_min_length_greater_than_max_length_rejected():
    assert "FIELD_CONSTRAINT_INVALID" in _codes(
        {"type": "string", "minLength": 5, "maxLength": 2}
    )


@pytest.mark.parametrize("key", ["minLength", "maxLength"])
def test_negative_length_rejected(key):
    assert "FIELD_CONSTRAINT_INVALID" in _codes({"type": "string", key: -1})


@pytest.mark.parametrize("key", ["min", "max"])
def test_numeric_constraint_on_non_numeric_rejected(key):
    assert "FIELD_CONSTRAINT_INVALID" in _codes({"type": "string", key: 1})


@pytest.mark.parametrize("key", ["minLength", "maxLength", "format"])
def test_string_constraint_on_non_string_rejected(key):
    value = "email" if key == "format" else 1
    assert "FIELD_CONSTRAINT_INVALID" in _codes({"type": "number", key: value})


def test_empty_enum_rejected():
    assert "FIELD_CONSTRAINT_INVALID" in _codes({"type": "enum", "values": []})


def test_default_outside_enum_rejected():
    assert "FIELD_CONSTRAINT_INVALID" in _codes(
        {"type": "enum", "values": ["a", "b"], "default": "c"}
    )


@pytest.mark.parametrize("field_type,default", [
    ("number", "abc"),
    ("string", True),
    ("string", ["a"]),
    ("number", {"a": 1}),
    ("boolean", "yes"),
])
def test_default_type_mismatch_rejected(field_type, default):
    assert "FIELD_CONSTRAINT_INVALID" in _codes({"type": field_type, "default": default})


def test_error_path_points_at_field():
    errors = _errors({"type": "number", "min": 10, "max": 1})
    assert errors[0].path == "entities.post.fields.value"


def test_nested_array_item_constraint_rejected():
    field = {"type": "array", "items": {"type": "number", "min": 5, "max": 1}}
    errors = _errors(field)
    assert errors[0].path == "entities.post.fields.value.items"


def test_nested_object_property_constraint_rejected():
    field = {
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": -1}},
    }
    errors = _errors(field)
    assert errors[0].path == "entities.post.fields.value.properties.name"


# ---- Currently-valid specs stay valid ----

def test_min_equals_max_accepted():
    assert _codes({"type": "number", "min": 5, "max": 5}) == set()


def test_required_with_default_accepted():
    assert _codes({"type": "string", "required": True, "default": "x"}) == set()


def test_default_null_accepted():
    assert _codes({"type": "number", "default": None}) == set()


def test_single_value_enum_accepted():
    assert _codes({"type": "enum", "values": ["only"], "default": "only"}) == set()


@pytest.mark.parametrize("field_type,default", [
    ("number", "42"),
    ("number", "3.5"),
    ("boolean", "true"),
    ("boolean", "0"),
])
def test_coercible_string_default_accepted(field_type, default):
    # An env-resolved ${VAR} default arrives as a numeric/boolean-looking string
    # that Pydantic coerces cleanly, so it must not be a false positive.
    assert _codes({"type": field_type, "default": default}) == set()


def test_non_coercible_string_default_on_number_rejected():
    assert "FIELD_CONSTRAINT_INVALID" in _codes({"type": "number", "default": "lots"})


def test_integer_default_on_number_accepted():
    assert _codes({"type": "number", "default": 3}) == set()


def test_valid_string_constraints_accepted():
    assert _codes(
        {"type": "string", "minLength": 0, "maxLength": 100, "format": "email"}
    ) == set()


# ---- Defaults conform to their own field config ----

@pytest.mark.parametrize("field", [
    {"type": "string", "format": "email", "default": "not-an-email"},
    {"type": "string", "maxLength": 2, "default": "long"},
    {"type": "number", "min": 5, "default": 1},
    {"type": "array", "items": {"type": "string", "maxLength": 1}, "default": ["ab"]},
    {"type": "array", "items": {"type": "number"}, "default": ["x"]},
    {"type": "object", "properties": {"a": {"type": "number"}}, "default": {"b": 1}},
    {"type": "object", "properties": {"a": {"type": "number", "required": True}}, "default": {}},
    {"type": "object", "properties": {"a": {"type": "number", "max": 1}}, "default": {"a": 2}},
])
def test_default_violating_its_own_config_rejected(field):
    assert "FIELD_CONSTRAINT_INVALID" in _codes(field)


@pytest.mark.parametrize("field", [
    {"type": "string", "format": "email", "default": "a@b.co"},
    {"type": "array", "items": {"type": "string", "maxLength": 1}, "default": ["a"]},
    {"type": "object", "properties": {"a": {"type": "number", "required": True}}, "default": {"a": 1}},
    {"type": "object", "default": {"free": "form"}},
])
def test_default_satisfying_its_own_config_accepted(field):
    assert _codes(field) == set()


# ---- End to end ----

def test_invalid_constraint_rejected_end_to_end(tmp_path):
    import yaml

    spec = {
        "version": "0.2",
        "api": {"basePath": "/api", "version": "v1"},
        "mongo": {"uri": "mongodb://localhost:27017", "database": "testdb"},
        "entities": {
            "post": {
                "fields": {
                    "id": {"type": "id"},
                    "rank": {"type": "number", "min": 10, "max": 1},
                }
            }
        },
        "repositories": {"posts": {"entity": "post"}},
        "services": {"posts": {"repository": "posts"}},
        "controllers": {
            "posts": {"service": "posts", "base_path": "/posts", "access": "public"}
        },
    }
    yaml_file = tmp_path / "spec.yaml"
    yaml_file.write_text(yaml.safe_dump(spec))
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(yaml_file))
    assert "FIELD_CONSTRAINT_INVALID" in {e.code for e in exc_info.value.errors}
