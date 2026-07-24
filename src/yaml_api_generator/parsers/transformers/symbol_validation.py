"""v0.3 undefined-symbol enforcement for repository query and where-binding scopes.

A repository operation's query resolves ``$<symbol>`` references against the
slugs of the routes that reach it; nothing else is ambient (there is no
principal or request root). An access-rule ``where`` binding resolves its
right-hand-side ``$<symbol>`` references against the route's declared slugs plus
the symbols the same rule binds in ``given:``. Any other free symbol -- a typo,
a service-supplied name not yet forwarded -- aborts generation with the single
``UNDEFINED_SYMBOL`` error naming the symbol and the scope. ``when`` operands are
enforced by the same scope model inside the access validator.
"""

from __future__ import annotations

import re
from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError
from yaml_api_generator.parsers.where_parser import WHERE_KEYWORD

from .symbol_resolution import SymbolScope

_SLUG = re.compile(r"\{(\w+)\}")
_RHS_SYMBOL = re.compile(r"\$(\w+)")


def validate_spec_symbols(spec: dict[str, Any]) -> list[ConfigError]:
    errors: list[ConfigError] = []
    errors.extend(_validate_repository_filters(spec))
    errors.extend(_validate_where_bindings(spec))
    errors.extend(_validate_service_with(spec))
    return errors


def _validate_service_with(spec: dict[str, Any]) -> list[ConfigError]:
    from yaml_api_generator.parsers.service_input_parser import parse_service_input

    dtos = spec.get("dto") or {}
    errors: list[ConfigError] = []
    for service_name, service in (spec.get("services") or {}).items():
        if not isinstance(service, dict) or not isinstance(service.get("with"), dict):
            continue
        input_ir, _ = parse_service_input(service.get("input"), dtos, "")
        bound = input_ir.names if input_ir is not None else frozenset()
        for name, value in service["with"].items():
            scope = SymbolScope(
                label=f"service '{service_name}' with '{name}'", bound=bound
            )
            path = f"services.{service_name}.with.{name}"
            errors.extend(scope.undefined(_where_rhs_symbols(str(value)), path))
    return errors


def _validate_repository_filters(spec: dict[str, Any]) -> list[ConfigError]:
    slugs = _slugs_by_operation(spec)
    errors: list[ConfigError] = []
    for repo_name, repo in (spec.get("repositories") or {}).items():
        if not isinstance(repo, dict):
            continue
        for op_name, op in (repo.get("operations") or {}).items():
            if not isinstance(op, dict) or not isinstance(op.get("query"), dict):
                continue
            scope = SymbolScope(
                label=f"repository '{repo_name}' operation '{op_name}' filter",
                bound=slugs.get((repo_name, op_name), frozenset()),
            )
            path = f"repositories.{repo_name}.operations.{op_name}.query"
            errors.extend(scope.undefined(_free_symbols(op["query"]), path))
    return errors


def _validate_where_bindings(spec: dict[str, Any]) -> list[ConfigError]:
    errors: list[ConfigError] = []
    for controller_name, controller in (spec.get("controllers") or {}).items():
        if not isinstance(controller, dict):
            continue
        base = str(controller.get("base_path", ""))
        for route_name, route in (controller.get("routes") or {}).items():
            if not isinstance(route, dict):
                continue
            slugs = frozenset(_SLUG.findall(base + str(route.get("path", ""))))
            access = route.get("access")
            rules = access if isinstance(access, list) else [access]
            for index, rule in enumerate(rules):
                if not isinstance(rule, dict) or not isinstance(rule.get("given"), dict):
                    continue
                given = rule["given"]
                bound = slugs | frozenset(given.keys())
                for name, value in given.items():
                    if not isinstance(value, str) or WHERE_KEYWORD not in value:
                        continue
                    scope = SymbolScope(
                        label=(
                            f"controller '{controller_name}' route '{route_name}' "
                            f"access[{index}] given '{name}' where"
                        ),
                        bound=bound,
                    )
                    path = (
                        f"controllers.{controller_name}.routes.{route_name}"
                        f".access[{index}].given.{name}"
                    )
                    errors.extend(scope.undefined(_where_rhs_symbols(value), path))
    return errors


def _where_rhs_symbols(value: str) -> set[str]:
    return {match.group(1) for match in _RHS_SYMBOL.finditer(value)}


def _free_symbols(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value[1:].split(".")[0]} if value.startswith("$") else set()
    if isinstance(value, dict):
        return set().union(*(_free_symbols(v) for v in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_free_symbols(v) for v in value), set())
    return set()


def _slugs_by_operation(spec: dict[str, Any]) -> dict[tuple[str, str], frozenset[str]]:
    services = spec.get("services") or {}
    reached: dict[tuple[str, str], set[str]] = {}
    for controller in (spec.get("controllers") or {}).values():
        if not isinstance(controller, dict):
            continue
        base = str(controller.get("base_path", ""))
        for route in (controller.get("routes") or {}).values():
            if not isinstance(route, dict):
                continue
            service = services.get(route.get("service"))
            if not isinstance(service, dict):
                continue
            repository, operation = service.get("repository"), service.get("operation")
            if repository is None or operation is None:
                continue
            route_slugs = set(_SLUG.findall(base + str(route.get("path", ""))))
            reached.setdefault((repository, operation), set()).update(route_slugs)
    return {key: frozenset(names) for key, names in reached.items()}
