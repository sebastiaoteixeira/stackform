"""Access control rule parsing with symbol resolution.

Parses access control rules from YAML into IRAccessRule objects.
"""

from typing import Any

from yaml_api_generator.ir import (
    IRAccessRule,
    IRDocumentBinding,
    IRIdentityBinding,
    IRRequestBinding,
)
from yaml_api_generator.parsers.yaml_parser import ConfigError
from yaml_api_generator.parsers.when_parser import parse_when_list
from yaml_api_generator.parsers.transformers.principal_resolver import resolve_principal
from yaml_api_generator.parsers.transformers.v02.binding_classifier import classify_binding


class AccessTransformer:
    """Parses access control rules with symbol resolution.

    ``allow_where`` enables the v0.3 ``where`` binding form for ``given:``
    values; v0.2 leaves it off so document bindings keep their implicit fetch.
    """

    def __init__(self, allow_where: bool = False) -> None:
        self._allow_where = allow_where

    def parse_access(
        self,
        access: Any,
        path: str,
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> tuple[bool, list[IRAccessRule] | None, list[ConfigError]]:
        """Parse access control configuration.

        Args:
            access: Raw access configuration value
            path: YAML path for error reporting
            auth_entities: Set of entity names marked as auth type
            entity_to_collection: Entity name to collection name mapping

        Returns:
            Tuple of (is_public, access_rules, errors)
            - is_public: True if access is public
            - access_rules: List of access rules if defined, None otherwise
            - errors: List of validation errors
        """
        if access is None:
            return False, None, []
        if access == "public":
            return True, None, []
        if access == "*":
            return False, None, []
        if isinstance(access, str):
            rule, errors = self._parse_access_string(
                access, path, auth_entities, entity_to_collection
            )
            if errors:
                return False, None, errors
            return False, ([rule] if rule is not None else None), []
        if isinstance(access, list):
            rules: list[IRAccessRule] = []
            errors: list[ConfigError] = []
            for i, item in enumerate(access):
                item_path = f"{path}[{i}]"
                if isinstance(item, str):
                    rule, str_errors = self._parse_access_string(
                        item, item_path, auth_entities, entity_to_collection
                    )
                    errors.extend(str_errors)
                    if rule is not None:
                        rules.append(rule)
                elif isinstance(item, dict):
                    rule, dict_errors = self._parse_access_rule_object(
                        item, item_path, auth_entities, entity_to_collection
                    )
                    errors.extend(dict_errors)
                    if rule is not None:
                        rules.append(rule)
            if errors:
                return False, None, errors
            return False, (rules if rules else None), []
        return False, None, []

    def _parse_access_string(
        self,
        value: str,
        path: str,
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> tuple[IRAccessRule | None, list[ConfigError]]:
        resolved, errors = resolve_principal(value, path, auth_entities, entity_to_collection)
        if resolved is None or resolved.is_public or resolved.principal is None:
            return None, errors
        return IRAccessRule(
            principal=resolved.principal, required_role=resolved.required_role
        ), errors

    def _parse_access_rule_object(
        self,
        rule: dict[str, Any],
        path: str,
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> tuple[IRAccessRule | None, list[ConfigError]]:
        errors: list[ConfigError] = []
        given = rule.get("given", {})
        effect = rule.get("then", "allow")

        identity_symbols: dict[str, IRIdentityBinding] = {}
        document_symbols: dict[str, IRDocumentBinding] = {}
        request_symbols: dict[str, IRRequestBinding] = {}

        if isinstance(given, dict):
            for symbol_name, symbol_value in given.items():
                if not isinstance(symbol_value, str):
                    continue
                binding, binding_errors = classify_binding(
                    symbol_value, f"{path}.given.{symbol_name}", entity_to_collection,
                    allow_where=self._allow_where,
                )
                errors.extend(binding_errors)
                if isinstance(binding, IRIdentityBinding):
                    identity_symbols[symbol_name] = binding
                elif isinstance(binding, IRRequestBinding):
                    request_symbols[symbol_name] = binding
                elif isinstance(binding, IRDocumentBinding):
                    document_symbols[symbol_name] = binding

        when_expr = None
        when_raw = rule.get("when")
        if when_raw is not None:
            when_expr, when_errors = parse_when_list(when_raw, f"{path}.when")
            errors.extend(when_errors)

        if errors:
            return None, errors

        first_identity = next(iter(identity_symbols.values()), None)
        principal = f"identity:{first_identity.collection_name}" if first_identity else ""

        return IRAccessRule(
            principal=principal,
            required_role=None,
            identity_symbols=identity_symbols,
            document_symbols=document_symbols,
            request_symbols=request_symbols,
            when=when_expr,
            effect=effect,
            filter=rule.get("filter"),
            write_fields=rule.get("writeFields", []),
            reason=rule.get("reason"),
        ), []
