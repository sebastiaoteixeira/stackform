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


def _matches_type(field_type: str, value: Any) -> bool:
    if field_type == "string":
        return isinstance(value, str)
    if field_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "array":
        return isinstance(value, list)
    if field_type == "object":
        return isinstance(value, dict)
    return True


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
        _check_default(field, field_type, path, errors)

    if field_type == "array" and isinstance(field.get("items"), dict):
        _check_field(field["items"], f"{path}.items", errors)
    if field_type == "object":
        for name, prop in (field.get("properties") or {}).items():
            if isinstance(prop, dict):
                _check_field(prop, f"{path}.properties.{name}", errors)


def _check_default(
    field: dict[str, Any], field_type: str, path: str, errors: list[ConfigError]
) -> None:
    default = field["default"]
    if default is None:
        return

    if field_type == "enum":
        values = field.get("values")
        if isinstance(values, list) and values and default not in values:
            errors.append(_error(
                f"default '{default}' is not one of the enum values {values}", path,
                "Set default to one of the listed values",
            ))
        return

    # Interpolation has already run, so a remaining string is a genuine literal.
    # Numbers and booleans coerce cleanly from numeric/boolean-looking strings
    # (e.g. an env-driven "${PORT:-8080}" default), so only flag strings that
    # cannot be coerced into the declared type.
    if not _matches_type(field_type, default):
        if isinstance(default, str) and _coerces_to(field_type, default):
            return
        errors.append(_error(
            f"default {default!r} does not match field type '{field_type}'", path,
            f"Provide a {field_type} default or remove it",
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


def validate_spec_constraints(spec: dict[str, Any], section: str = "entities") -> list[ConfigError]:
    """Validate field-constraint coherence across every model of ``section``."""
    errors: list[ConfigError] = []
    for model_name, model in (spec.get(section) or {}).items():
        if not isinstance(model, dict):
            continue
        for field_name, field in (model.get("fields") or {}).items():
            if isinstance(field, dict):
                _check_field(
                    field, f"{section}.{model_name}.fields.{field_name}", errors
                )
    return errors
