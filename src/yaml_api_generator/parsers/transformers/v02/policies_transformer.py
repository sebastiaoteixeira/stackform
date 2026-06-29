"""Parses the top-level ``policies:`` block into IRPolicy objects.

A policy is a named reusable when-fragment. Its ``given`` values use the same
binding grammar as access-rule ``given``; its ``params`` are caller-supplied
symbol names; its ``when`` is parsed with the shared when parser. Symbol
binding checks and reference resolution are performed later (policy validation
and the expansion pass) -- this transformer only builds the IR.
"""

import re
from typing import Any

from yaml_api_generator.ir import IRBinding, IRPolicy
from yaml_api_generator.parsers.yaml_parser import ConfigError
from yaml_api_generator.parsers.when_parser import parse_when_list
from yaml_api_generator.parsers.transformers.v02.binding_classifier import classify_binding

_POLICY_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


class PoliciesTransformer:
    """Parses reusable access policies."""

    def transform(
        self,
        policies_data: dict[str, Any],
        entity_to_collection: dict[str, str],
    ) -> tuple[dict[str, IRPolicy], list[ConfigError]]:
        policies: dict[str, IRPolicy] = {}
        errors: list[ConfigError] = []

        for name, cfg in policies_data.items():
            path = f"policies.{name}"
            if not _POLICY_NAME_RE.match(name):
                errors.append(ConfigError(
                    code="POLICY_NAME_INVALID",
                    message=f"Invalid policy name '{name}'",
                    path=path,
                    hint="Policy names must match ^[a-zA-Z][a-zA-Z0-9_]*$",
                ))
                continue
            if not isinstance(cfg, dict):
                continue

            given: dict[str, IRBinding] = {}
            for symbol_name, symbol_value in (cfg.get("given") or {}).items():
                binding, binding_errors = classify_binding(
                    symbol_value, f"{path}.given.{symbol_name}", entity_to_collection
                )
                errors.extend(binding_errors)
                if binding is not None:
                    given[symbol_name] = binding

            params = tuple(cfg.get("params") or [])

            when_raw = cfg.get("when")
            when_expr, when_errors = parse_when_list(when_raw, f"{path}.when")
            for error in when_errors:
                errors.append(ConfigError(
                    code="POLICY_PARSE_ERROR",
                    message=f"policy '{name}': {error.message}",
                    path=error.path,
                    hint=error.hint,
                ))
            if when_expr is None:
                continue

            policies[name] = IRPolicy(
                name=name, when=when_expr, given=given, params=params
            )

        return policies, errors
