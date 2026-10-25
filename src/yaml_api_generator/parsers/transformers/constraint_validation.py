"""Semantic coherence checks for field constraints, in every field map of a spec.

The JSON schema decides which keys a field of each type may carry. What it
cannot express is the relation between values: a lower bound above its upper
bound, or a ``default`` its own field would reject. These checks run on the
pre-desugar spec, so the rejection happens once for all targets.
"""

from collections.abc import Iterator
from typing import Any

from yaml_api_generator.parsers.transformers.field_defaults import canonical_default
from yaml_api_generator.parsers.transformers.field_maps import spec_fields
from yaml_api_generator.parsers.yaml_parser import ConfigError

_BOUNDS = (("min", "max"), ("minLength", "maxLength"))


def _error(message: str, path: str, hint: str) -> ConfigError:
    return ConfigError(
        code="FIELD_CONSTRAINT_INVALID", message=message, path=path, hint=hint
    )


def _check_field(field: dict[str, Any], path: str) -> Iterator[ConfigError]:
    for low, high in _BOUNDS:
        lower, upper = field.get(low), field.get(high)
        if lower is not None and upper is not None and lower > upper:
            yield _error(
                f"{low} ({lower}) is greater than {high} ({upper})", path,
                f"Ensure {low} is less than or equal to {high}",
            )
    if "default" in field:
        yield from _check_default(field, path)
    if isinstance(field.get("items"), dict):
        yield from _check_field(field["items"], f"{path}.items")
    for name, prop in (field.get("properties") or {}).items():
        if isinstance(prop, dict):
            yield from _check_field(prop, f"{path}.properties.{name}")


def _check_default(field: dict[str, Any], path: str) -> Iterator[ConfigError]:
    """A default must satisfy its own field config, nested properties and items included."""
    try:
        canonical_default(field, path)
    except ValueError as error:
        yield _error(
            f"default {field['default']!r} is invalid: {error}", path,
            "Make the default satisfy the field's own constraints or remove it",
        )


def validate_spec_constraints(spec: dict[str, Any]) -> list[ConfigError]:
    """Validate field-constraint coherence across every field map in the spec."""
    return [
        error
        for path, field in spec_fields(spec)
        for error in _check_field(field, path)
    ]
