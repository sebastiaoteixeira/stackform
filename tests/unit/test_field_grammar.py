"""Field configs in every version and every field map: keys by type, bounds, defaults and refs."""

import pytest
import yaml

from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

VERSIONS = ("0.1", "0.2", "0.3")


def _entity_spec(version: str, field: dict) -> dict:
    if version == "0.1":
        return {"version": "0.1", "collections": {"things": {"fields": {"id": {"type": "id"}, "f": field}}}}
    return {
        "version": version,
        "entities": {"thing": {"fields": {"id": {"type": "id"}, "f": field}}},
        "repositories": {"things": {"entity": "thing"}},
        "services": {"things": {"repository": "things"}},
        "controllers": {"things": {"service": "things", "base_path": "/things", "access": "public"}},
    }


def _dto_spec(version: str, field: dict) -> dict:
    spec = _entity_spec(version, {"type": "string"})
    spec["dto"] = {"thingInput": {"fields": {"f": field}}}
    return spec


def _codes(tmp_path, spec: dict) -> set[str]:
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec))
    try:
        load_and_generate_ir(path)
    except ConfigErrors as raised:
        return {error.code for error in raised.errors}
    return set()


INAPPLICABLE = [
    {"type": "string", "items": {"type": "string"}},
    {"type": "string", "properties": {}},
    {"type": "string", "additionalProperties": False},
    {"type": "string", "values": ["a"]},
    {"type": "string", "ref": "thing"},
    {"type": "string", "min": 1},
    {"type": "number", "format": "email"},
    {"type": "number", "minLength": 1},
    {"type": "boolean", "maxLength": 1},
    {"type": "array", "items": {"type": "string"}, "minLength": 1},
    {"type": "string", "minLength": -1},
    {"type": "enum", "values": []},
    {"type": "string", "format": "uuidv4x"},
    {"type": "object", "properties": {"a": {"type": "string", "unique": True}}},
    {"type": "object", "properties": {"a": {"type": "number", "format": "email"}}},
    {"type": "array", "items": {"type": "string", "unique": True}},
]
INCOHERENT = [
    {"type": "number", "min": 5, "max": 1},
    {"type": "string", "minLength": 5, "maxLength": 1},
    {"type": "enum", "values": ["a"], "default": "b"},
    {"type": "number", "max": 1, "default": 5},
    {"type": "string", "format": "email", "default": "x"},
    {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "additionalProperties": False,
        "default": {"a": "x", "b": 1},
    },
    {"type": "object", "properties": {"a": {"type": "number", "min": 5, "max": 1}}},
]
DANGLING = [
    {"type": "ref", "ref": "ghost"},
    {"type": "array", "items": {"type": "ref", "ref": "ghost"}},
    {"type": "object", "properties": {"a": {"type": "ref", "ref": "ghost"}}},
]
VALID = [
    {"type": "string", "format": "email", "minLength": 1, "default": "a@b.co"},
    {"type": "number", "min": 1, "max": 1, "default": 1},
    {"type": "enum", "values": ["a"], "default": "a"},
    {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "number"}}}},
    {"type": "object", "properties": {"a": {"type": "string", "format": "uri"}}, "additionalProperties": False},
]


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("field", INAPPLICABLE)
def test_inapplicable_key_fails_schema_validation(tmp_path, version, field):
    assert _codes(tmp_path, _entity_spec(version, field)) == {"SCHEMA_VALIDATION_ERROR"}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("field", INCOHERENT)
def test_incoherent_constraint_is_rejected(tmp_path, version, field):
    assert _codes(tmp_path, _entity_spec(version, field)) == {"FIELD_CONSTRAINT_INVALID"}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("field", DANGLING)
def test_ref_to_undeclared_record_is_rejected(tmp_path, version, field):
    assert _codes(tmp_path, _entity_spec(version, field)) == {"REF_TARGET_NOT_FOUND"}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("field", VALID)
def test_coherent_field_is_accepted(tmp_path, version, field):
    assert _codes(tmp_path, _entity_spec(version, field)) == set()


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("field", [
    *INAPPLICABLE,
    {"type": "id"},
    {"type": "string", "unique": True},
    {"type": "string", "readonly": True, "foo": 1},
])
def test_inapplicable_dto_key_fails_schema_validation(tmp_path, version, field):
    assert _codes(tmp_path, _dto_spec(version, field)) == {"SCHEMA_VALIDATION_ERROR"}


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("field", INCOHERENT)
def test_incoherent_dto_constraint_is_rejected(tmp_path, version, field):
    assert _codes(tmp_path, _dto_spec(version, field)) == {"FIELD_CONSTRAINT_INVALID"}


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("field", VALID)
def test_coherent_dto_field_is_accepted(tmp_path, version, field):
    assert _codes(tmp_path, _dto_spec(version, field)) == set()


def test_incoherent_service_input_default_is_rejected(tmp_path):
    spec = _entity_spec("0.3", {"type": "string"})
    spec["services"]["things"]["input"] = {"n": {"type": "number", "max": 1, "default": 5}}
    assert _codes(tmp_path, spec) == {"FIELD_CONSTRAINT_INVALID"}
