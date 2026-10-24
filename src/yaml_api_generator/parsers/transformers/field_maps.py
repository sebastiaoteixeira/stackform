"""The field maps a spec declares, in every version, keyed by their dotted path."""

from collections.abc import Iterable, Iterator
from typing import Any

# Each section maps an owner name to a config whose field map sits under this key.
FIELD_MAP_KEYS = {
    "collections": "fields",
    "entities": "fields",
    "dto": "fields",
    "services": "input",
}
RECORD_SECTIONS = ("collections", "entities")


def field_maps(
    spec: dict[str, Any], sections: Iterable[str] = FIELD_MAP_KEYS
) -> Iterator[tuple[str, dict[str, Any]]]:
    """The ``(path, fields)`` of every field map declared in ``sections``."""
    for section in sections:
        key = FIELD_MAP_KEYS[section]
        for name, owner in (spec.get(section) or {}).items():
            fields = owner.get(key) if isinstance(owner, dict) else None
            if isinstance(fields, dict):
                yield f"{section}.{name}.{key}", fields


def spec_fields(
    spec: dict[str, Any], sections: Iterable[str] = FIELD_MAP_KEYS
) -> Iterator[tuple[str, dict[str, Any]]]:
    """The ``(path, field)`` of every top-level field config declared in ``sections``."""
    for base, fields in field_maps(spec, sections):
        for name, field in fields.items():
            if isinstance(field, dict):
                yield f"{base}.{name}", field
