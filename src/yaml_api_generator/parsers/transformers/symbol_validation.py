"""v0.3 undefined-symbol enforcement for repository query and where-binding scopes.

A repository operation's query resolves ``$<symbol>`` references against the
slugs of the routes that reach it; nothing else is ambient (there is no
principal or request root). An access-rule ``where`` binding resolves its
right-hand-side ``$<symbol>`` references against the same namespace the runtime
builds for the predicate fetch: the route's declared slugs plus the identity and
request symbols the rule binds in ``given:``. Document symbols -- including the
binding itself -- are fetched by that step, so they are not in scope. Any other
free symbol aborts generation with the single ``UNDEFINED_SYMBOL`` error naming
the symbol and the scope. The predicate's left-hand-side field must be declared
on the collection's entity; an unknown one aborts with ``WHERE_FIELD_UNKNOWN``.
``when`` operands are enforced by the same scope model inside the access
validator.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError
from yaml_api_generator.parsers.where_parser import WhereBinding, parse_where_binding

from .auth_validation import _resolved_fields
from .symbol_resolution import SymbolScope
from .v02.binding_classifier import BindingKind, binding_kind

WHERE_FIELD_UNKNOWN = "WHERE_FIELD_UNKNOWN"

_SLUG = re.compile(r"\{(\w+)\}")
_WHERE_NAMESPACE_KINDS = frozenset({BindingKind.IDENTITY, BindingKind.REQUEST})


def validate_spec_symbols(spec: dict[str, Any]) -> list[ConfigError]:
    errors: list[ConfigError] = []
    errors.extend(_validate_repository_filters(spec))
    errors.extend(_validate_where_bindings(spec))
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


@dataclass(frozen=True)
class _AccessRuleSite:
    label: str
    path: str
    slugs: frozenset[str]
    given: dict[str, Any]

    def where_errors(
        self, fields_by_collection: dict[str, frozenset[str]]
    ) -> list[ConfigError]:
        kinds = {
            name: binding_kind(value, allow_where=True)
            for name, value in self.given.items()
            if isinstance(value, str)
        }
        bound = self.slugs | frozenset(
            name for name, kind in kinds.items() if kind in _WHERE_NAMESPACE_KINDS
        )
        return [
            error
            for name, kind in kinds.items()
            if kind is BindingKind.WHERE
            for error in self._binding_errors(name, bound, fields_by_collection)
        ]

    def _binding_errors(
        self,
        name: str,
        bound: frozenset[str],
        fields_by_collection: dict[str, frozenset[str]],
    ) -> list[ConfigError]:
        path = f"{self.path}.given.{name}"
        binding, _ = parse_where_binding(self.given[name], path)
        if binding is None:
            return []
        scope = SymbolScope(label=f"{self.label} given '{name}' where", bound=bound)
        return scope.undefined(binding.symbols, path) + _unknown_fields(
            binding, fields_by_collection, path
        )


def _validate_where_bindings(spec: dict[str, Any]) -> list[ConfigError]:
    fields_by_collection = _fields_by_collection(spec)
    return [
        error
        for site in _access_rule_sites(spec)
        for error in site.where_errors(fields_by_collection)
    ]


def _access_rule_sites(spec: dict[str, Any]) -> Iterator[_AccessRuleSite]:
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
                yield _AccessRuleSite(
                    label=(
                        f"controller '{controller_name}' route '{route_name}' "
                        f"access[{index}]"
                    ),
                    path=(
                        f"controllers.{controller_name}.routes.{route_name}"
                        f".access[{index}]"
                    ),
                    slugs=slugs,
                    given=rule["given"],
                )


def _unknown_fields(
    binding: WhereBinding,
    fields_by_collection: dict[str, frozenset[str]],
    path: str,
) -> list[ConfigError]:
    fields = fields_by_collection.get(binding.collection)
    if fields is None:
        return []
    return [
        ConfigError(
            code=WHERE_FIELD_UNKNOWN,
            message=(
                f"where field '{conjunct.field}' is not declared on collection "
                f"'{binding.collection}'"
            ),
            path=path,
            hint=f"Declare '{conjunct.field}' on the collection's entity or fix the typo",
        )
        for conjunct in binding.conjuncts
        if conjunct.field not in fields
    ]


def _fields_by_collection(spec: dict[str, Any]) -> dict[str, frozenset[str]]:
    entities = spec.get("entities") or {}
    return {
        name: frozenset(_resolved_fields(repo["entity"], entities))
        for name, repo in (spec.get("repositories") or {}).items()
        if isinstance(repo, dict) and isinstance(entities.get(repo.get("entity")), dict)
    }


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
