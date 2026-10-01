"""Placement checks for ``type: file`` fields and the unsupported-target guard.

A file field lives only at the top level of an entity, alone or as the items of
a top-level array: its bytes sit in a file datastore and its record value is
fixed metadata. Nested objects, DTOs and service inputs therefore cannot carry
one. These checks run on the pre-desugar spec, mirroring
``validate_spec_constraints``.
"""

from collections.abc import Iterator, Mapping
from typing import Any

from yaml_api_generator.parsers.errors import ConfigError, ConfigErrors


def file_config(field: Any) -> dict[str, Any] | None:
    """The ``type: file`` config of a single or array-of-files field, else None."""
    if not isinstance(field, dict):
        return None
    if field.get("type") == "file":
        return field
    items = field.get("items")
    if field.get("type") == "array" and isinstance(items, dict) and items.get("type") == "file":
        return items
    return None


def file_nodes(field: Any, path: str) -> Iterator[str]:
    """Paths of every ``type: file`` node within a field tree."""
    if not isinstance(field, dict):
        return
    if field.get("type") == "file":
        yield path
    yield from file_nodes(field.get("items"), f"{path}.items")
    properties = field.get("properties")
    if isinstance(properties, dict):
        for name, prop in properties.items():
            yield from file_nodes(prop, f"{path}.properties.{name}")


def file_context_errors(field: Any, path: str, context: str) -> list[ConfigError]:
    """Reject file nodes in a field tree that belongs to a non-entity ``context``."""
    return [
        ConfigError(
            code="FILE_FIELD_CONTEXT_INVALID",
            message=f"file fields cannot be declared in {context}",
            path=node,
            hint="Declare file fields on an entity and upload through its routes",
        )
        for node in file_nodes(field, path)
    ]


def _entity_fields(spec: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    for entity_name, entity in (spec.get("entities") or {}).items():
        fields = entity.get("fields") if isinstance(entity, dict) else None
        if isinstance(fields, dict):
            for field_name, field in fields.items():
                yield f"entities.{entity_name}.fields.{field_name}", field


def validate_spec_files(spec: dict[str, Any]) -> list[ConfigError]:
    """Reject file fields nested below an entity's top level."""
    errors: list[ConfigError] = []
    for path, field in _entity_fields(spec):
        top = file_config(field)
        allowed = None if top is None else path if top is field else f"{path}.items"
        errors.extend(
            ConfigError(
                code="FILE_FIELD_NESTED",
                message="file fields are allowed only at the top level of an entity",
                path=node,
                hint="Move the file to a top-level field or a top-level array of files",
            )
            for node in file_nodes(field, path)
            if node != allowed
        )
    return errors


def reject_file_fields(collections: Mapping[str, Mapping[str, Any]], target: str) -> None:
    """Raise when any entity declares a file field on a target that cannot serve files.

    ``collections`` maps each entity name to its raw ``fields`` dict.
    """
    first = next(
        (
            f"entities.{owner}.fields.{name}"
            for owner, fields in collections.items()
            for name, field in fields.items()
            if file_config(field) is not None
        ),
        None,
    )
    if first is not None:
        raise ConfigErrors([ConfigError(
            code="BACKEND_FEATURE_UNSUPPORTED",
            message=f"file fields are not supported by target '{target}'",
            path=first,
            hint="Generate for the 'fastapi' backend, or remove file fields",
        )])
