"""v0.3 undefined-symbol enforcement for repository query and where-binding scopes.

A repository operation's query resolves ``$<symbol>`` references against the
slugs of the routes that reach it; nothing else is ambient (there is no
principal or request root). Access-rule ``where`` and ``bind`` expressions
resolve references against the same pre-authorization namespace: route slugs
plus identity and request symbols declared by that rule's ``given:`` mapping.
Document symbols are unavailable until their fetch completes. Any other free
symbol aborts generation with ``UNDEFINED_SYMBOL``. A ``where`` predicate field
must exist on the collection entity or generation aborts with
``WHERE_FIELD_UNKNOWN``. ``when`` operands use the same scope model through the
access validator.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError
from yaml_api_generator.ir import IRSymbolRef
from yaml_api_generator.parsers.where_parser import WhereBinding, parse_where_binding

from .entity_inheritance import inherited_fields
from .symbol_resolution import SymbolScope
from .v02.binding_classifier import BindingKind, binding_kind

WHERE_FIELD_UNKNOWN = "WHERE_FIELD_UNKNOWN"
ROUTE_LOCATOR_FIELD_UNKNOWN = "ROUTE_LOCATOR_FIELD_UNKNOWN"
BIND_MISSING_REQUIRED_INPUT = "BIND_MISSING_REQUIRED_INPUT"
BIND_TARGET_UNKNOWN = "BIND_TARGET_UNKNOWN"
BIND_DOCUMENT_RULE_UNSUPPORTED = "BIND_DOCUMENT_RULE_UNSUPPORTED"

_SLUG = re.compile(r"\{(\w+)\}")
_WHERE_NAMESPACE_KINDS = frozenset({BindingKind.IDENTITY, BindingKind.REQUEST})
_RECORD_OPERATIONS = frozenset({"get", "update", "replace", "delete"})


def validate_spec_symbols(spec: dict[str, Any]) -> list[ConfigError]:
    errors: list[ConfigError] = []
    errors.extend(_validate_repository_filters(spec))
    errors.extend(_validate_where_bindings(spec))
    errors.extend(_validate_access_bind(spec))
    errors.extend(_validate_service_with(spec))
    errors.extend(_validate_record_locators(spec))
    return errors


def _validate_service_with(spec: dict[str, Any]) -> list[ConfigError]:
    if str(spec.get("version")) != "0.3":
        return []

    from yaml_api_generator.parsers.service_input_parser import (
        parse_service_input,
        parse_service_with,
    )

    dtos = spec.get("dto") or {}
    repositories = spec.get("repositories") or {}
    errors: list[ConfigError] = []
    for service_name, service in (spec.get("services") or {}).items():
        if not isinstance(service, dict) or not isinstance(service.get("with"), dict):
            continue
        input_ir = None
        if "input" in service:
            input_ir, input_errors = parse_service_input(
                service["input"], dtos, f"services.{service_name}.input"
            )
            errors.extend(input_errors)
        bound = input_ir.names if input_ir is not None else frozenset()
        forwarding, forwarding_errors = parse_service_with(
            service["with"], f"services.{service_name}.with"
        )
        errors.extend(forwarding_errors)
        for name, rhs in forwarding.items():
            scope = SymbolScope(
                label=f"service '{service_name}' with '{name}'", bound=bound
            )
            path = f"services.{service_name}.with.{name}"
            symbols = {rhs.root} if isinstance(rhs, IRSymbolRef) else set()
            errors.extend(scope.undefined(symbols, path))
        repository = repositories.get(service.get("repository"))
        if service.get("handler") or not isinstance(repository, dict):
            continue
        operation = service.get("operation")
        operation_config = (repository.get("operations") or {}).get(operation)
        query = operation_config.get("query") if isinstance(operation_config, dict) else None
        referenced = _free_symbols(query) if isinstance(query, dict) else set()
        errors.extend(
            ConfigError(
                code="SERVICE_WITH_TARGET_UNKNOWN",
                message=(
                    f"service '{service_name}' forwards '{name}', but repository "
                    f"operation '{operation}' does not reference '${name}'"
                ),
                path=f"services.{service_name}.with.{name}",
                hint="Remove the forwarding or reference the name in the operation query",
            )
            for name in forwarding
            if name not in referenced
        )
    return errors


def _validate_record_locators(spec: dict[str, Any]) -> list[ConfigError]:
    services = spec.get("services") or {}
    fields_by_collection = _fields_by_collection(spec)
    errors: list[ConfigError] = []
    for controller_name, controller in (spec.get("controllers") or {}).items():
        if not isinstance(controller, dict):
            continue
        base = str(controller.get("base_path", ""))
        for route_name, route in (controller.get("routes") or {}).items():
            if not isinstance(route, dict):
                continue
            service = services.get(route.get("service"))
            if not isinstance(service, dict):
                continue
            operation = service.get("operation") or route_name
            repository = service.get("repository")
            fields = fields_by_collection.get(repository)
            tokens = _SLUG.findall(base + str(route.get("path", "")))
            if operation not in _RECORD_OPERATIONS or fields is None or not tokens:
                continue
            path = f"controllers.{controller_name}.routes.{route_name}.path"
            errors.extend(
                ConfigError(
                    code=ROUTE_LOCATOR_FIELD_UNKNOWN,
                    message=(
                        f"route scope token '{token}' is not declared on collection "
                        f"'{repository}'"
                    ),
                    path=path,
                    hint=(
                        f"Declare '{token}' on the collection's entity or use a "
                        "where binding for a different field mapping"
                    ),
                )
                for token in tokens[:-1]
                if token not in fields
            )
    return errors


def _validate_repository_filters(spec: dict[str, Any]) -> list[ConfigError]:
    sites = _repository_filter_sites(spec)
    errors: list[ConfigError] = []
    for repo_name, repo in (spec.get("repositories") or {}).items():
        if not isinstance(repo, dict):
            continue
        for op_name, op in (repo.get("operations") or {}).items():
            if not isinstance(op, dict) or not isinstance(op.get("query"), dict):
                continue
            path = f"repositories.{repo_name}.operations.{op_name}.query"
            operation_sites = sites.get((repo_name, op_name)) or [
                (f"repository '{repo_name}' operation '{op_name}' filter", frozenset())
            ]
            for label, bound in operation_sites:
                scope = SymbolScope(label=label, bound=bound)
                errors.extend(scope.undefined(_free_symbols(op["query"]), path))
    return errors


def _repository_filter_sites(
    spec: dict[str, Any],
) -> dict[tuple[str, str], list[tuple[str, frozenset[str]]]]:
    services = spec.get("services") or {}
    sites: dict[tuple[str, str], list[tuple[str, frozenset[str]]]] = {}
    for controller_name, controller in (spec.get("controllers") or {}).items():
        if not isinstance(controller, dict):
            continue
        base = str(controller.get("base_path", ""))
        for route_name, route in (controller.get("routes") or {}).items():
            if not isinstance(route, dict):
                continue
            service = services.get(route.get("service"))
            if not isinstance(service, dict):
                continue
            repository = service.get("repository")
            operation = service.get("operation") or route_name
            if repository is None:
                continue
            slugs = frozenset(_SLUG.findall(base + str(route.get("path", ""))))
            forwarding = service.get("with")
            supplied = slugs | (
                frozenset(forwarding) if isinstance(forwarding, dict) else frozenset()
            )
            label = (
                f"repository '{repository}' operation '{operation}' filter for "
                f"controller '{controller_name}' route '{route_name}'"
            )
            sites.setdefault((repository, operation), []).append((label, supplied))
    return sites


@dataclass(frozen=True)
class _AccessRuleSite:
    label: str
    path: str
    slugs: frozenset[str]
    rule: dict[str, Any]
    service_name: str | None
    route_has_document_rule: bool

    @property
    def given(self) -> dict[str, Any]:
        given = self.rule.get("given")
        return given if isinstance(given, dict) else {}

    @property
    def bound(self) -> frozenset[str]:
        return self.slugs | frozenset(
            name
            for name, value in self.given.items()
            if isinstance(value, str)
            and binding_kind(value, allow_where=True) in _WHERE_NAMESPACE_KINDS
        )

    def where_errors(
        self, fields_by_collection: dict[str, frozenset[str]]
    ) -> list[ConfigError]:
        kinds = {
            name: binding_kind(value, allow_where=True)
            for name, value in self.given.items()
            if isinstance(value, str)
        }
        return [
            error
            for name, kind in kinds.items()
            if kind is BindingKind.WHERE
            for error in self._binding_errors(name, fields_by_collection)
        ]

    def bind_errors(
        self,
        dtos: dict[str, Any],
        services: dict[str, Any],
    ) -> list[ConfigError]:
        bind = self.rule.get("bind")
        if not isinstance(bind, dict):
            return []

        from yaml_api_generator.parsers.service_input_parser import (
            parse_service_input,
            parse_service_with,
        )

        forwarding, parse_errors = parse_service_with(bind, f"{self.path}.bind")
        scope = SymbolScope(label=f"{self.label} bind", bound=self.bound)
        errors = parse_errors + [
            error
            for name, rhs in forwarding.items()
            if isinstance(rhs, IRSymbolRef)
            for error in scope.undefined({rhs.root}, f"{self.path}.bind.{name}")
        ]
        if self.route_has_document_rule:
            errors.append(
                ConfigError(
                    code=BIND_DOCUMENT_RULE_UNSUPPORTED,
                    message=f"{self.label} cannot combine bind with a document rule",
                    path=f"{self.path}.bind",
                    hint="Use only identity/request bindings on a route with bind",
                )
            )

        service = services.get(self.service_name)
        input_ir = None
        if isinstance(service, dict) and service.get("input") is not None:
            input_ir, _ = parse_service_input(
                service["input"], dtos, f"services.{self.service_name}.input"
            )
        input_fields = input_ir.fields if input_ir is not None else {}
        errors.extend(
            ConfigError(
                code=BIND_TARGET_UNKNOWN,
                message=(
                    f"{self.label} binds '{name}', but service "
                    f"'{self.service_name}' does not declare that input"
                ),
                path=f"{self.path}.bind.{name}",
                hint="Declare the service input or remove this bind target",
            )
            for name in forwarding
            if name not in input_fields
        )
        supplied = self.slugs | frozenset(forwarding)
        errors.extend(
            ConfigError(
                code=BIND_MISSING_REQUIRED_INPUT,
                message=f"{self.label} bind omits required service input '{name}'",
                path=f"{self.path}.bind",
                hint=f"Bind '{name}' or declare it as a route path parameter",
            )
            for name, config in input_fields.items()
            if config.get("required", True) and name not in supplied
        )
        return errors

    def _binding_errors(
        self,
        name: str,
        fields_by_collection: dict[str, frozenset[str]],
    ) -> list[ConfigError]:
        path = f"{self.path}.given.{name}"
        binding, _ = parse_where_binding(self.given[name], path)
        if binding is None:
            return []
        scope = SymbolScope(label=f"{self.label} given '{name}' where", bound=self.bound)
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


def _validate_access_bind(spec: dict[str, Any]) -> list[ConfigError]:
    if str(spec.get("version")) != "0.3":
        return []
    dtos = spec.get("dto") or {}
    services = spec.get("services") or {}
    return [
        error
        for site in _access_rule_sites(spec)
        for error in site.bind_errors(dtos, services)
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
            route_has_document_rule = any(
                isinstance(candidate, dict)
                and isinstance(candidate.get("given"), dict)
                and any(
                    isinstance(value, str)
                    and binding_kind(value, allow_where=True)
                    in (BindingKind.DOCUMENT, BindingKind.WHERE)
                    for value in candidate["given"].values()
                )
                for candidate in rules
            )
            for index, rule in enumerate(rules):
                if not isinstance(rule, dict):
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
                    rule=rule,
                    service_name=(
                        str(route["service"]) if route.get("service") is not None else None
                    ),
                    route_has_document_rule=route_has_document_rule,
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
        name: frozenset(inherited_fields(repo["entity"], entities))
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
