"""v0.3 undefined-symbol enforcement for repository query scopes.

A repository operation's query resolves ``$<symbol>`` references against the
slugs of the routes that reach it; nothing else is ambient (there is no
principal or request root). Any other free symbol -- ``$principal``, a typo, a
service-supplied name not yet forwarded -- aborts generation with the single
``UNDEFINED_SYMBOL`` error naming the symbol and the scope. ``when`` operands are
enforced by the same scope model inside the access validator.
"""

from __future__ import annotations

import re
from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError

from .symbol_resolution import SymbolScope

_SLUG = re.compile(r"\{(\w+)\}")


def validate_spec_symbols(spec: dict[str, Any]) -> list[ConfigError]:
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
