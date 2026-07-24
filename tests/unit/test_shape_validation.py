import pytest

from yaml_api_generator.parsers.transformers.shape_validation import validate_spec_shape
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

# Wrong-shape repros: each top-level block desugar dereferences as a mapping,
# authored as a list or scalar, must yield a clean SCHEMA_VALIDATION_ERROR
# instead of a raw AttributeError out of desugar.
WRONG_SHAPES = {
    "entities-string": ({"entities": "foo"}, "entities"),
    "entities-list": ({"entities": ["a"]}, "entities"),
    "repositories-list": ({"repositories": ["a"]}, "repositories"),
    "services-list": ({"services": ["a"]}, "services"),
    "api-scalar": ({"api": "foo"}, "api"),
    "api-operations-list": ({"api": {"operations": ["a"]}}, "api.operations"),
}


@pytest.mark.parametrize("spec,path", WRONG_SHAPES.values(), ids=list(WRONG_SHAPES))
def test_validate_spec_shape_flags_wrong_container(spec, path):
    errors = validate_spec_shape(spec)
    assert [(e.code, e.path) for e in errors] == [("SCHEMA_VALIDATION_ERROR", path)]


def test_validate_spec_shape_accepts_mappings():
    spec = {
        "entities": {"items": {}},
        "repositories": {},
        "services": {},
        "controllers": {},
        "api": {"operations": {}},
    }
    assert validate_spec_shape(spec) == []


@pytest.mark.parametrize("spec,path", WRONG_SHAPES.values(), ids=list(WRONG_SHAPES))
def test_load_reports_clean_schema_error(tmp_path, spec, path):
    import yaml

    yaml_file = tmp_path / "spec.yaml"
    yaml_file.write_text(yaml.safe_dump({"version": "0.2", **spec}))
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(yaml_file))
    errors = exc_info.value.errors
    assert any(e.code == "SCHEMA_VALIDATION_ERROR" and e.path == path for e in errors)


def test_auth_bindings_key_rejected(tmp_path):
    import yaml

    spec = {
        "version": "0.2",
        "entities": {
            "user": {
                "type": "auth",
                "auth": {
                    "identifier": "email",
                    "via": "password",
                    "bindings": [{"provider": "keycloak"}],
                },
                "fields": {"id": {"type": "id"}, "email": {"type": "string"}},
            }
        },
    }
    yaml_file = tmp_path / "spec.yaml"
    yaml_file.write_text(yaml.safe_dump(spec))
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(yaml_file))
    assert any(e.code == "SCHEMA_VALIDATION_ERROR" for e in exc_info.value.errors)
