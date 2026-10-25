"""Field defaults in the form their own field gives a request value.

Every consumer stores a default as the spec declares it, so the spec carries
each default already conformed: a datetime in its canonical UTC form, an object
with its nested defaults filled in. Interpolation leaves an env-driven number
or boolean default (``${PORT:-8080}``) as a string, which is read as its type.
"""

from typing import Any

from yaml_api_generator.parsers.transformers.field_maps import field_maps
from yaml_api_generator.parsers.transformers.file_validation import file_config
from yaml_api_generator.runtime.fields import conform

_BOOLEANS = {"true": True, "1": True, "false": False, "0": False}


def _typed(field_type: Any, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if field_type == "number":
        try:
            return float(value)
        except ValueError:
            return value
    if field_type == "boolean":
        return _BOOLEANS.get(value.lower(), value)
    return value


def canonical_default(field: dict[str, Any], path: str = "default") -> Any:
    """``field``'s default as its field conforms it; a ``ValueError`` when the field rejects it."""
    default = field["default"]
    if default is None or file_config(field) is not None:
        return default
    return conform(field, _typed(field.get("type"), default), path)


def _canonical_field(field: Any) -> Any:
    if not isinstance(field, dict):
        return field
    nested = {
        **({"items": _canonical_field(field["items"])} if "items" in field else {}),
        **(
            {"properties": {name: _canonical_field(prop) for name, prop in field["properties"].items()}}
            if isinstance(field.get("properties"), dict)
            else {}
        ),
    }
    canonical = {**field, **nested}
    return {**canonical, "default": canonical_default(canonical)} if "default" in canonical else canonical


def canonicalize_defaults(spec: dict[str, Any]) -> None:
    """Replace every default in ``spec``'s field maps, nested ones included, with its canonical form."""
    for _, fields in field_maps(spec):
        fields.update({name: _canonical_field(field) for name, field in fields.items()})

