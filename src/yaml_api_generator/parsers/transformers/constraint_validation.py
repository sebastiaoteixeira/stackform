"""Semantic coherence checks for field constraints in a v0.2 spec.

The generator copies ``min``/``max``/``minLength``/``maxLength``/``default`` and
``values`` straight into Pydantic and DRF models. The JSON schema only checks
each key's own type, so impossible or mismatched constraints (``min`` above
``max``, ``minLength`` on a number, a ``default`` outside an ``enum``) reach the
models silently and either crash at import time or produce models that reject
every input. These checks run on the pre-desugar spec, mirroring
``validate_spec_names``, so the rejection happens once for all targets.
"""

from typing import Any

from yaml_api_generator.parsers.transformers.file_validation import file_config
from yaml_api_generator.parsers.yaml_parser import ConfigError
from yaml_api_generator.runtime.fields import conform

# Constraints only meaningful for a given field type. min/max belong to numbers;
# minLength/maxLength belong to strings. format is shared by string and id
# (where uuidv4/uuidv7 select the key generator), so it is checked separately.
_NUMERIC_ONLY = ("min", "max")
_STRING_ONLY = ("minLength", "maxLength")
_FORMAT_TYPES = ("string", "id")
# File limits apply to file nodes; a file's record value is upload metadata, so
# it can be neither unique nor defaulted.
_FILE_ONLY = ("maxSize", "types", "disposition")
_FILE_FORBIDDEN = ("unique", "default")


def _error(message: str, path: str, hint: str) -> ConfigError:
    return ConfigError(
        code="FIELD_CONSTRAINT_INVALID", message=message, path=path, hint=hint
    )


def _check_field(field: dict[str, Any], path: str, errors: list[ConfigError]) -> None:
    field_type = field.get("type")

    minimum, maximum = field.get("min"), field.get("max")
    if minimum is not None and maximum is not None and minimum > maximum:
        errors.append(_error(
            f"min ({minimum}) is greater than max ({maximum})", path,
            "Ensure min is less than or equal to max",
        ))
    min_len, max_len = field.get("minLength"), field.get("maxLength")
    if min_len is not None and max_len is not None and min_len > max_len:
        errors.append(_error(
            f"minLength ({min_len}) is greater than maxLength ({max_len})", path,
            "Ensure minLength is less than or equal to maxLength",
        ))
    for key in ("minLength", "maxLength"):
        value = field.get(key)
        if value is not None and value < 0:
            errors.append(_error(
                f"{key} ({value}) must not be negative", path,
                f"Set {key} to zero or a positive integer",
            ))

    if field_type != "number":
        for key in _NUMERIC_ONLY:
            if field.get(key) is not None:
                errors.append(_error(
                    f"{key} is only valid on number fields, not '{field_type}'", path,
                    "Use minLength/maxLength for strings or remove the constraint",
                ))
    if field_type != "string":
        for key in _STRING_ONLY:
            if field.get(key) is not None:
                errors.append(_error(
                    f"{key} is only valid on string fields, not '{field_type}'", path,
                    "Use min/max for numbers or remove the constraint",
                ))
    if field.get("format") is not None and field_type not in _FORMAT_TYPES:
        errors.append(_error(
            f"format is only valid on string or id fields, not '{field_type}'", path,
            "Remove format or change the field type",
        ))

    if field_type != "file":
        for key in _FILE_ONLY:
            if field.get(key) is not None:
                errors.append(_error(
                    f"{key} is only valid on file fields, not '{field_type}'", path,
                    "Remove the constraint or change the field type to file",
                ))
    else:
        for key in _FILE_FORBIDDEN:
            if key in field:
                errors.append(_error(
                    f"{key} is not valid on file fields", path,
                    f"Remove {key} from the file field",
                ))
    if field.get("maxItems") is not None and (field_type == "file" or file_config(field) is None):
        errors.append(_error(
            "maxItems is only valid on arrays of files", path,
            "Remove maxItems or declare the field as an array of files",
        ))

    if field_type == "enum":
        values = field.get("values")
        if values == []:
            errors.append(_error(
                "enum field has no values", path,
                "List at least one allowed value",
            ))

    if "default" in field:
        _check_default(field, path, errors)

    if field_type == "array" and isinstance(field.get("items"), dict):
        _check_field(field["items"], f"{path}.items", errors)
    if field_type == "object":
        for name, prop in (field.get("properties") or {}).items():
            if isinstance(prop, dict):
                _check_field(prop, f"{path}.properties.{name}", errors)


def _check_default(field: dict[str, Any], path: str, errors: list[ConfigError]) -> None:
    """A default must satisfy its own field config, nested properties and items included.

    Interpolation has already run, so a numeric or boolean looking string is an
    env-driven default (``${PORT:-8080}``) and is accepted for its type.
    """
    default = field["default"]
    if default is None or file_config(field) is not None:
        return
    if isinstance(default, str) and _coerces_to(field.get("type"), default):
        return
    try:
        conform(field, default, path)
    except ValueError as error:
        errors.append(_error(
            f"default {default!r} is invalid: {error}", path,
            "Make the default satisfy the field's own constraints or remove it",
        ))


def _coerces_to(field_type: str, value: str) -> bool:
    if field_type == "number":
        try:
            float(value)
        except ValueError:
            return False
        return True
    if field_type == "boolean":
        return value.lower() in ("true", "false", "1", "0")
    return False


def validate_spec_constraints(spec: dict[str, Any]) -> list[ConfigError]:
    """Validate field-constraint coherence across every entity in the spec."""
    errors: list[ConfigError] = []
    for entity_name, entity in (spec.get("entities") or {}).items():
        if not isinstance(entity, dict):
            continue
        for field_name, field in (entity.get("fields") or {}).items():
            if isinstance(field, dict):
                _check_field(
                    field, f"entities.{entity_name}.fields.{field_name}", errors
                )
    return errors
