"""Semantic coherence checks for access-control rules in a v0.2 spec.

Access rules drive authorization in every target (generated FastAPI/DRF
backends and the in-process run server). The JSON schema only validates each
key's shape, so several security-relevant mistakes pass schema validation yet
silently mis-authorize at runtime. These checks run on the pre-desugar spec,
mirroring ``validate_spec_constraints``, and reject the spec with coded errors:

- WHEN_UNBOUND_SYMBOL: a ``when`` field reference whose root is not bound in
  the rule's ``given`` symbols. An unbound root (e.g. ``ghost.sub``) evaluates
  against a missing symbol and silently neuters the rule.
- ACCESS_RULE_INVALID: covers the remaining contradictions and ambiguities --
  a role not declared in the entity's ``roles.values``; a document-dependent
  ``when`` on a CREATE operation (pre-fetch authorization short-circuits
  document rules to allow, turning a create-ownership rule into allow-everyone);
  an empty ``access: []`` list; and two rules for the same principal+condition
  with opposite allow/deny effects.
"""

from typing import Any

from yaml_api_generator.ir.when import collect_roots, needs_document
from yaml_api_generator.parsers.when_parser import parse_request_binding, parse_when_list
from yaml_api_generator.parsers.yaml_parser import ConfigError

# Operations whose route is a POST create: pre-fetch authorization runs with no
# document, so any document-dependent rule on them is short-circuited to allow.
_CREATE_OPERATIONS = frozenset({"create", "register"})

# Operations whose request carries no body: binding request.body / request:<type>
# on them can never resolve.
_BODILESS_OPERATIONS = frozenset({"get", "list", "delete"})

_PRIMITIVE_TYPES = frozenset({"string", "number", "boolean", "datetime"})


def _is_request_value(value: Any) -> bool:
    return isinstance(value, str) and (
        value == "request" or value.startswith(("request.", "request:"))
    )


def _invalid(message: str, path: str, hint: str) -> ConfigError:
    return ConfigError(
        code="ACCESS_RULE_INVALID", message=message, path=path, hint=hint
    )


def _declared_roles(spec: dict[str, Any]) -> dict[str, frozenset[str]]:
    """Map each auth entity to the role names it declares.

    Roles may be declared via ``roles.values`` and/or the enum role field named
    by ``auth.roles`` (defaulting to ``role``). The declared set is their union,
    so a role used in access is valid if either source lists it.
    """
    roles: dict[str, frozenset[str]] = {}
    for entity_name, entity in (spec.get("entities") or {}).items():
        if not isinstance(entity, dict):
            continue
        names: set[str] = set()
        values = (entity.get("roles") or {}).get("values")
        if isinstance(values, list):
            names.update(str(value) for value in values)

        auth = entity.get("auth") or {}
        role_field = auth.get("roles", "role") if isinstance(auth, dict) else "role"
        field = (entity.get("fields") or {}).get(role_field)
        if isinstance(field, dict) and isinstance(field.get("values"), list):
            names.update(str(value) for value in field["values"])

        if names:
            roles[entity_name] = frozenset(names)
    return roles


def _auth_entities(spec: dict[str, Any]) -> set[str]:
    return {
        name
        for name, entity in (spec.get("entities") or {}).items()
        if isinstance(entity, dict) and str(entity.get("type", "base")) == "auth"
    }


def _check_role_string(
    value: str,
    path: str,
    declared_roles: dict[str, frozenset[str]],
    auth_entities: set[str],
    errors: list[ConfigError],
) -> None:
    if value in ("public", "*"):
        return

    if ":" in value:
        entity, role = value.split(":", 1)
        if entity not in auth_entities or role == "*":
            return
        _check_role_declared(role, entity, declared_roles, path, errors)
        return

    # Unscoped role: meaningful only with a single auth entity (the transformer
    # rejects the ambiguous multi-entity case), so validate against that entity.
    if len(auth_entities) == 1:
        entity = next(iter(auth_entities))
        _check_role_declared(value, entity, declared_roles, path, errors)


def _check_role_declared(
    role: str,
    entity: str,
    declared_roles: dict[str, frozenset[str]],
    path: str,
    errors: list[ConfigError],
) -> None:
    # An entity that declares no roles at all gives nothing to check against, so
    # skip rather than reject every role as undeclared.
    declared = declared_roles.get(entity)
    if declared and role not in declared:
        errors.append(_invalid(
            f"role '{role}' is not declared in entity '{entity}'", path,
            f"Add '{role}' to entities.{entity}.roles.values or fix the typo",
        ))


def _check_when(
    rule: dict[str, Any], path: str, errors: list[ConfigError], is_create: bool
) -> Any | None:
    when_raw = rule.get("when")
    if when_raw is None:
        return None

    expr, when_errors = parse_when_list(when_raw, f"{path}.when")
    if when_errors:
        errors.extend(when_errors)
        return None

    bound = set((rule.get("given") or {}).keys())
    for root in collect_roots(expr):
        if root not in bound:
            errors.append(ConfigError(
                code="WHEN_UNBOUND_SYMBOL",
                message=f"when references unbound symbol '{root}'",
                path=f"{path}.when",
                hint=f"Bind '{root}' in this rule's 'given'",
            ))

    if is_create and (needs_document(expr) or rule.get("document_symbols")):
        errors.append(_invalid(
            "document-dependent when on a create rule is short-circuited to allow",
            f"{path}.when",
            "Drop the document condition or move this rule to a non-create operation",
        ))
    return expr


def _check_request_bindings(
    given: dict[str, Any],
    path: str,
    op_name: str | None,
    known_types: frozenset[str],
    errors: list[ConfigError],
) -> None:
    for symbol_name, value in given.items():
        if not _is_request_value(value):
            continue
        binding_path = f"{path}.given.{symbol_name}"
        parsed, parse_errors = parse_request_binding(value, binding_path)
        errors.extend(parse_errors)
        if parsed is None:
            continue
        part, type_name, _ = parsed
        binds_body = part is None or part == "body"
        if binds_body and op_name in _BODILESS_OPERATIONS:
            errors.append(ConfigError(
                code="REQUEST_BODY_ON_BODILESS_OP",
                message=f"request body bound on bodiless operation '{op_name}'",
                path=binding_path,
                hint="body bindings apply only to create/update/replace",
            ))
        if (
            type_name is not None
            and type_name not in _PRIMITIVE_TYPES
            and type_name not in known_types
        ):
            errors.append(ConfigError(
                code="REQUEST_TYPE_NOT_FOUND",
                message=f"request type '{type_name}' is not a primitive, entity or dto",
                path=binding_path,
            ))


def _check_rule_list(
    access: list[Any],
    path: str,
    declared_roles: dict[str, frozenset[str]],
    auth_entities: set[str],
    is_create: bool,
    op_name: str | None,
    known_types: frozenset[str],
    errors: list[ConfigError],
) -> None:
    if access == []:
        errors.append(_invalid(
            "access is an empty list", path,
            "List at least one rule, or use 'public'/'*'",
        ))
        return

    seen: dict[tuple[str, Any], str] = {}
    for index, item in enumerate(access):
        item_path = f"{path}[{index}]"
        if isinstance(item, str):
            _check_role_string(
                item, item_path, declared_roles, auth_entities, errors
            )
            _track_contradiction(item, "allow", item_path, seen, errors)
        elif isinstance(item, dict):
            given = item.get("given") or {}
            if isinstance(given, dict):
                _check_request_bindings(
                    given, item_path, op_name, known_types, errors
                )
            given_doc = isinstance(given, dict) and any(
                isinstance(value, str)
                and not value.startswith("identity:")
                and not _is_request_value(value)
                for value in given.values()
            )
            expr = _check_when(
                {**item, "document_symbols": given_doc}, item_path, errors, is_create
            )
            effect = item.get("then", "allow")
            principal = next(
                (str(v) for v in given.values() if isinstance(v, str)
                 and v.startswith("identity:")),
                "",
            )
            _track_contradiction((principal, expr), effect, item_path, seen, errors)


def _track_contradiction(
    key: Any, effect: str, path: str, seen: dict, errors: list[ConfigError]
) -> None:
    if key in seen and seen[key] != effect:
        errors.append(_invalid(
            f"contradictory rules for the same principal and condition: "
            f"'{seen[key]}' and '{effect}'",
            path,
            "Remove one of the conflicting allow/deny rules",
        ))
    else:
        seen.setdefault(key, effect)


def _check_access(
    access: Any,
    path: str,
    declared_roles: dict[str, frozenset[str]],
    auth_entities: set[str],
    is_create: bool,
    op_name: str | None,
    known_types: frozenset[str],
    errors: list[ConfigError],
) -> None:
    if isinstance(access, str):
        _check_role_string(access, path, declared_roles, auth_entities, errors)
    elif isinstance(access, list):
        _check_rule_list(
            access, path, declared_roles, auth_entities,
            is_create, op_name, known_types, errors,
        )


def _is_always_allow_rule(rule: Any) -> bool:
    if not isinstance(rule, dict):
        return False
    given = rule.get("given")
    when = rule.get("when")
    return not given and when is None


def _warn_access_rules(
    access: Any, path: str, warnings: list[ConfigError]
) -> None:
    if not isinstance(access, list):
        return
    for index, rule in enumerate(access):
        if _is_always_allow_rule(rule):
            warnings.append(ConfigError(
                code="PUBLIC_ROUTE",
                message=f"Access rule at '{path}[{index}]' has no principal or condition",
                path=f"{path}[{index}]",
                hint="Add a 'given:' principal or 'when:' condition to restrict access",
                severity="warning",
            ))


def warn_public_routes(spec: dict[str, Any]) -> list[ConfigError]:
    """Return warnings for routes that admit any unauthenticated caller."""
    warnings: list[ConfigError] = []
    for controller_name, controller in (spec.get("controllers") or {}).items():
        if not isinstance(controller, dict):
            continue
        base = f"controllers.{controller_name}"
        for section in ("operations", "routes"):
            for op_name, op in (controller.get(section) or {}).items():
                if not isinstance(op, dict):
                    continue
                path = f"{base}.{section}.{op_name}"
                if "access" not in op:
                    warnings.append(ConfigError(
                        code="PUBLIC_ROUTE",
                        message=f"Route '{path}' has no access control",
                        path=path,
                        hint="Add an 'access:' block to restrict this route",
                        severity="warning",
                    ))
                else:
                    _warn_access_rules(op["access"], path, warnings)
    return warnings


def validate_spec_access(spec: dict[str, Any]) -> list[ConfigError]:
    """Validate access-rule coherence across every controller in the spec."""
    errors: list[ConfigError] = []
    declared_roles = _declared_roles(spec)
    auth_entities = _auth_entities(spec)
    known_types = frozenset(
        (spec.get("entities") or {}).keys() | (spec.get("dto") or {}).keys()
    )

    for controller_name, controller in (spec.get("controllers") or {}).items():
        if not isinstance(controller, dict):
            continue
        base = f"controllers.{controller_name}"
        if "access" in controller:
            _check_access(
                controller["access"], f"{base}.access",
                declared_roles, auth_entities, False, None, known_types, errors,
            )
        for section in ("operations", "routes"):
            for op_name, op in (controller.get(section) or {}).items():
                if not isinstance(op, dict) or "access" not in op:
                    continue
                _check_access(
                    op["access"], f"{base}.{section}.{op_name}.access",
                    declared_roles, auth_entities,
                    op_name in _CREATE_OPERATIONS, op_name, known_types, errors,
                )
    return errors
