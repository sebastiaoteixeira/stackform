"""Reference targets of ``type: ref`` fields on records.

REF_TARGET_NOT_FOUND: an entity (or v0.1 collection) field, at any nesting
depth, references a name that is not a declared entity (or collection).
"""

from collections.abc import Iterator
from typing import Any

from yaml_api_generator.parsers.transformers.field_maps import RECORD_SECTIONS, field_maps
from yaml_api_generator.parsers.yaml_parser import ConfigError


def field_refs(fields: dict[str, Any], base: str) -> Iterator[tuple[str, str]]:
    """The ``(path, target)`` of every ref field, inside object properties and array items too."""
    for name, field in fields.items():
        if isinstance(field, dict):
            yield from _refs(field, f"{base}.{name}")


def _refs(field: dict[str, Any], path: str) -> Iterator[tuple[str, str]]:
    if field.get("type") == "ref" and isinstance(field.get("ref"), str):
        yield f"{path}.ref", field["ref"]
    if isinstance(field.get("items"), dict):
        yield from _refs(field["items"], f"{path}.items")
    if isinstance(field.get("properties"), dict):
        yield from field_refs(field["properties"], f"{path}.properties")


def validate_spec_refs(spec: dict[str, Any]) -> list[ConfigError]:
    records = sorted(name for section in RECORD_SECTIONS for name in spec.get(section) or {})
    return [
        ConfigError(
            code="REF_TARGET_NOT_FOUND",
            message=f"Field references undeclared record type '{target}'",
            path=path,
            hint=f"Declare '{target}' or reference one of: {', '.join(records)}",
        )
        for base, fields in field_maps(spec, RECORD_SECTIONS)
        for path, target in field_refs(fields, base)
        if target not in records
    ]
