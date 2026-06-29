"""Semantic checks for top-level ``dto`` declarations in a v0.2 spec.

A DTO carries fields and validators only; persistence-shaped attributes belong
to entities, never to request-bound payload types. The schema accepts a DTO
field as a plain ``FieldConfig``, so these checks reject the persistence subset
the spec forbids:

- DTO_FORBIDS_PERSISTENCE_ATTR: a DTO field declares ``type: id``, ``unique`` or
  ``format``.
- DTO_NOT_FOUND: a DTO field references a type that is neither a declared entity
  nor a declared DTO.
"""

from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError

_FORBIDDEN_ATTRS = ("unique", "format")


def validate_spec_dtos(spec: dict[str, Any]) -> list[ConfigError]:
    errors: list[ConfigError] = []
    dtos = spec.get("dto") or {}
    known_refs = frozenset((spec.get("entities") or {}).keys() | dtos.keys())
    for dto_name, dto in dtos.items():
        if not isinstance(dto, dict):
            continue
        for field_name, field in (dto.get("fields") or {}).items():
            if not isinstance(field, dict):
                continue
            base = f"dto.{dto_name}.fields.{field_name}"
            if field.get("type") == "id":
                errors.append(_forbidden("type: id", base))
            for attr in _FORBIDDEN_ATTRS:
                if attr in field:
                    errors.append(_forbidden(attr, f"{base}.{attr}"))
            ref = field.get("ref")
            if field.get("type") == "ref" and ref is not None and ref not in known_refs:
                errors.append(ConfigError(
                    code="DTO_NOT_FOUND",
                    message=f"DTO field references undeclared type '{ref}'",
                    path=f"{base}.ref",
                ))
    return errors


def _forbidden(attr: str, path: str) -> ConfigError:
    return ConfigError(
        code="DTO_FORBIDS_PERSISTENCE_ATTR",
        message=f"DTO field declares persistence attribute '{attr}'",
        path=path,
        hint="DTOs carry validation only; move persistence attrs to an entity",
    )
