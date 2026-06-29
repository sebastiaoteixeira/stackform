"""Semantic coherence checks for reusable access policies.

Policies are named reusable when-fragments referenced as ``policy:name(args)``
terms inside access rules. The JSON schema validates each key's shape; these
checks enforce the policy contract before access coherence and expansion run:

- POLICY_PARSE_ERROR: a policy ``when`` fails the when parser (tagged with name).
- POLICY_UNBOUND_SYMBOL: a policy ``when`` references a root that is not bound
  in that policy's own ``given`` or ``params`` (rule symbols are out of scope).
- POLICY_NOT_FOUND: a reference to an undefined policy.
- POLICY_ARITY_MISMATCH: a reference whose arg count differs from the policy's
  declared params.
- POLICY_CYCLE: cyclic policy references (a -> b -> a).
"""

from typing import Any

from yaml_api_generator.ir.when import PolicyRef, collect_roots
from yaml_api_generator.parsers.when_parser import parse_when_list
from yaml_api_generator.parsers.yaml_parser import ConfigError


def _policy_refs(expr: Any) -> list[PolicyRef]:
    if isinstance(expr, PolicyRef):
        return [expr]
    refs: list[PolicyRef] = []
    for attr in ("left", "right", "operand"):
        child = getattr(expr, attr, None)
        if child is not None:
            refs.extend(_policy_refs(child))
    return refs


def _parsed_policies(
    policies: dict[str, Any], errors: list[ConfigError]
) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for name, cfg in policies.items():
        if not isinstance(cfg, dict):
            continue
        expr, parse_errors = parse_when_list(cfg.get("when"), f"policies.{name}.when")
        for error in parse_errors:
            errors.append(ConfigError(
                code="POLICY_PARSE_ERROR",
                message=f"policy '{name}': {error.message}",
                path=error.path,
                hint=error.hint,
            ))
        if expr is not None:
            parsed[name] = expr
    return parsed


def _check_bound_symbols(
    policies: dict[str, Any], parsed: dict[str, Any], errors: list[ConfigError]
) -> None:
    for name, expr in parsed.items():
        cfg = policies[name]
        bound = set((cfg.get("given") or {}).keys()) | set(cfg.get("params") or [])
        for root in collect_roots(expr):
            if root not in bound:
                errors.append(ConfigError(
                    code="POLICY_UNBOUND_SYMBOL",
                    message=f"policy '{name}' references unbound symbol '{root}'",
                    path=f"policies.{name}.when",
                    hint=f"Bind '{root}' in this policy's 'given' or 'params'",
                ))


def _check_refs(
    name: str, expr: Any, policies: dict[str, Any], path: str, errors: list[ConfigError]
) -> None:
    for ref in _policy_refs(expr):
        cfg = policies.get(ref.name)
        if cfg is None:
            errors.append(ConfigError(
                code="POLICY_NOT_FOUND",
                message=f"reference to undefined policy '{ref.name}'",
                path=path,
            ))
            continue
        params = cfg.get("params") or [] if isinstance(cfg, dict) else []
        if len(ref.args) != len(params):
            errors.append(ConfigError(
                code="POLICY_ARITY_MISMATCH",
                message=(
                    f"policy '{ref.name}' expects {len(params)} arg(s), "
                    f"got {len(ref.args)}"
                ),
                path=path,
            ))


def _check_cycles(
    parsed: dict[str, Any], policies: dict[str, Any], errors: list[ConfigError]
) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, trail: tuple[str, ...]) -> bool:
        if name in visiting:
            cycle = " -> ".join((*trail, name))
            errors.append(ConfigError(
                code="POLICY_CYCLE",
                message=f"cyclic policy references: {cycle}",
                path=f"policies.{name}.when",
            ))
            return True
        if name in visited or name not in parsed:
            return False
        visiting.add(name)
        for ref in _policy_refs(parsed[name]):
            if ref.name in policies and visit(ref.name, (*trail, name)):
                visiting.discard(name)
                visited.add(name)
                return True
        visiting.discard(name)
        visited.add(name)
        return False

    for name in parsed:
        visit(name, ())


def validate_spec_policies(spec: dict[str, Any]) -> list[ConfigError]:
    """Validate the policy table and every policy reference in the spec."""
    policies = spec.get("policies") or {}
    errors: list[ConfigError] = []

    parsed = _parsed_policies(policies, errors)
    _check_bound_symbols(policies, parsed, errors)

    for name, expr in parsed.items():
        _check_refs(name, expr, policies, f"policies.{name}.when", errors)

    if not any(e.code == "POLICY_NOT_FOUND" for e in errors):
        _check_cycles(parsed, policies, errors)

    for controller_name, controller in (spec.get("controllers") or {}).items():
        if not isinstance(controller, dict):
            continue
        base = f"controllers.{controller_name}"
        for section in ("operations", "routes"):
            for op_name, op in (controller.get(section) or {}).items():
                if not isinstance(op, dict):
                    continue
                _check_access_refs(
                    op.get("access"),
                    f"{base}.{section}.{op_name}.access",
                    policies, errors,
                )
        _check_access_refs(controller.get("access"), f"{base}.access", policies, errors)

    return errors


def _check_access_refs(
    access: Any, path: str, policies: dict[str, Any], errors: list[ConfigError]
) -> None:
    if not isinstance(access, list):
        return
    for index, item in enumerate(access):
        if not isinstance(item, dict) or "when" not in item:
            continue
        expr, parse_errors = parse_when_list(item["when"], f"{path}[{index}].when")
        if parse_errors or expr is None:
            continue
        _check_refs("", expr, policies, f"{path}[{index}].when", errors)
