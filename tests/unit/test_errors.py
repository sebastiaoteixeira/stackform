import pytest

from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from tests.conftest import INVALID_DIR, VALID_DIR


def test_missing_entity_ref_raises() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "missing-entity-ref.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert codes & {"DESUGAR_ENTITY_NOT_FOUND", "ENTITY_NOT_FOUND", "SCHEMA_VALIDATION_ERROR"}


def test_missing_entity_ref_error_codes() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "missing-entity-ref.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert codes & {"DESUGAR_ENTITY_NOT_FOUND", "ENTITY_NOT_FOUND"}


def test_abstract_entity_in_repo_raises() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "abstract-entity-in-repo.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "DESUGAR_ABSTRACT_REFERENCED" in codes


def test_yaml_parse_error_code() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "malformed-yaml.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "YAML_PARSE_ERROR" in codes


def test_yaml_root_invalid_error_code() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "root-is-list.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "YAML_ROOT_INVALID" in codes
    err = exc_info.value.errors[0]
    assert err.path == "$"


def test_interpolation_missing_var_error_code() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "env-missing-var.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "INTERPOLATION_MISSING_VAR" in codes
    err = next(
        e for e in exc_info.value.errors if e.code == "INTERPOLATION_MISSING_VAR"
    )
    assert "MISSING_VAR_NO_DEFAULT" in err.message
    assert err.hint is not None


def test_unsupported_version_error_code() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "version-unsupported.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "UNSUPPORTED_VERSION" in codes
    err = next(e for e in exc_info.value.errors if e.code == "UNSUPPORTED_VERSION")
    assert "0.3" in err.message


def test_schema_validation_error_code() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "schema-validation-fail.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "SCHEMA_VALIDATION_ERROR" in codes


def test_schema_load_error_unreadable() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(
            str(VALID_DIR / "v01-no-access-defaults.yaml"),
            schema_file="/nonexistent/schema.json",
        )
    codes = {e.code for e in exc_info.value.errors}
    assert "SCHEMA_LOAD_ERROR" in codes


def test_v01_no_id_field_error() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "v01-no-id-field.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "ID_FIELD_MISSING" in codes


def test_v01_multiple_id_fields_error() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "v01-multiple-id-fields.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "ID_FIELD_MULTIPLE" in codes


def test_v01_password_field_forbidden_error() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "v01-password-field-forbidden.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "AUTH_PASSWORD_FIELD_FORBIDDEN" in codes
    assert "AUTH_PASSWORD_HASH_FIELD_FORBIDDEN" in codes
