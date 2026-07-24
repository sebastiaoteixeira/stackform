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

from yaml_api_generator.ir import IRServiceInput, WhereRhs

from .where_parser import parse_rhs_value
from .yaml_parser import ConfigError


def parse_service_input(
    config: Any, dtos: dict[str, Any], path: str
) -> tuple[IRServiceInput | None, list[ConfigError]]:
    if isinstance(config, list):
        return _merge_dtos(config, dtos, path)
    if isinstance(config, dict):
        return IRServiceInput(fields=_normalize_inline(config)), []
    return None, [
        ConfigError(
            code="SERVICE_INPUT_INVALID",
            message="service input must be a list of DTO names or a field map",
            path=path,
        )
    ]


def parse_service_with(
    config: dict[str, Any], path: str
) -> tuple[dict[str, WhereRhs], list[ConfigError]]:
    bindings: dict[str, WhereRhs] = {}
    errors: list[ConfigError] = []
    for name, raw in config.items():
        rhs, rhs_errors = parse_rhs_value(str(raw), f"{path}.{name}")
        if rhs is None:
            errors.extend(rhs_errors)
            continue
        bindings[name] = rhs
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
    return IRServiceInput(fields=fields), []


def _normalize_inline(config: dict[str, Any]) -> dict[str, Any]:
    return {
        name: spec if isinstance(spec, dict) else {"type": spec}
        for name, spec in config.items()
    }
