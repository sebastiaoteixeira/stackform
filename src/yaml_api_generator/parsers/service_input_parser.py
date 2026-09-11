"""Parser for the v0.3 service ``input:`` declaration and ``with:`` forwarding.

``input:`` names the fields a service requires before it runs. It is either an
inline field map (``{postId: string}``) or a list of named DTOs whose fields are
merged. ``with:`` maps a downstream name (a repository free-symbol or a handler
kwarg) to a right-hand-side value drawn from the declared inputs -- a ``$symbol``
naming an input field, or a literal. The forwarding target is left implicit in
the IR (a service's repository or handler), keeping the shape open to services
that later fan out across several repositories.
"""

from __future__ import annotations

from typing import Any

from yaml_api_generator.ir import IRLiteralRef, IRServiceInput, WhereRhs

from .where_parser import parse_rhs_value
from .yaml_parser import ConfigError


def parse_service_input(
    config: Any, dtos: dict[str, Any], path: str
) -> tuple[IRServiceInput | None, list[ConfigError]]:
    if isinstance(config, list) and config:
        return _merge_dtos(config, dtos, path)
    if isinstance(config, dict) and config:
        fields = _normalize_inline(config)
        errors = _validate_fields(fields, path)
        return (None, errors) if errors else (IRServiceInput(fields=fields), [])
    return None, [
        ConfigError(
            code="SERVICE_INPUT_INVALID",
            message="service input must be a non-empty DTO list or field map",
            path=path,
        )
    ]


def parse_service_with(
    config: dict[str, Any], path: str
) -> tuple[dict[str, WhereRhs], list[ConfigError]]:
    bindings: dict[str, WhereRhs] = {}
    errors: list[ConfigError] = []
    for name, raw in config.items():
        value_path = f"{path}.{name}"
        if isinstance(raw, str) and raw.startswith("$"):
            rhs, rhs_errors = parse_rhs_value(raw, value_path)
            errors.extend(rhs_errors)
            if rhs is not None:
                bindings[name] = rhs
        elif isinstance(raw, (str, int, float, bool)):
            bindings[name] = IRLiteralRef(raw)
        else:
            errors.append(
                ConfigError(
                    code="SERVICE_WITH_VALUE_INVALID",
                    message="service with value must be a $symbol or scalar literal",
                    path=value_path,
                )
            )
    return bindings, errors


def _merge_dtos(
    names: list[Any], dtos: dict[str, Any], path: str
) -> tuple[IRServiceInput | None, list[ConfigError]]:
    fields: dict[str, Any] = {}
    errors: list[ConfigError] = []
    for name in names:
        dto = dtos.get(name)
        if not isinstance(dto, dict):
            errors.append(
                ConfigError(
                    code="SERVICE_INPUT_DTO_NOT_FOUND",
                    message=f"service input references undefined DTO '{name}'",
                    path=path,
                )
            )
            continue
        fields.update(_normalize_inline(dto.get("fields", {})))
    if errors:
        return None, errors
    field_errors = _validate_fields(fields, path)
    return (None, field_errors) if field_errors else (IRServiceInput(fields=fields), [])


def _normalize_inline(config: dict[str, Any]) -> dict[str, Any]:
    return {
        name: spec if isinstance(spec, dict) else {"type": spec}
        for name, spec in config.items()
    }


_FIELD_TYPES = frozenset(
    {"string", "number", "boolean", "datetime", "enum", "array", "object", "ref"}
)


def _validate_fields(fields: dict[str, Any], path: str) -> list[ConfigError]:
    errors: list[ConfigError] = []
    for name, config in fields.items():
        field_path = f"{path}.{name}"
        field_type = config.get("type", "string") if isinstance(config, dict) else None
        if field_type not in _FIELD_TYPES:
            errors.append(
                ConfigError(
                    code="SERVICE_INPUT_FIELD_INVALID",
                    message=f"service input '{name}' has invalid type '{field_type}'",
                    path=field_path,
                    hint=f"Use one of: {', '.join(sorted(_FIELD_TYPES))}",
                )
            )
        if isinstance(config, dict) and not isinstance(config.get("required", True), bool):
            errors.append(
                ConfigError(
                    code="SERVICE_INPUT_FIELD_INVALID",
                    message=f"service input '{name}' required flag must be boolean",
                    path=field_path,
                )
            )
    return errors
