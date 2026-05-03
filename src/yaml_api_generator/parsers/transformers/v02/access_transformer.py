"""Access control rule parsing with symbol resolution.

Parses access control rules from YAML into IRAccessRule objects.
"""

from typing import Any

from yaml_api_generator.ir import IRAccessRule, IRDocumentBinding, IRIdentityBinding
from yaml_api_generator.parsers.yaml_parser import ConfigError
from yaml_api_generator.parsers.when_parser import parse_document_binding, parse_when_list


class AccessTransformer:
    """Parses access control rules with symbol resolution."""

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
        if access is None or access == "public":
            return True, None, []
        if access in ("*", "authenticated"):
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
        return True, None, []

    def _parse_access_string(
        self,
        value: str,
        path: str,
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> tuple[IRAccessRule | None, list[ConfigError]]:
        if value in ("public", "*", "authenticated"):
            return None, []

        if value.startswith("identity:"):
            entity_name = value[len("identity:"):]
            collection = entity_to_collection.get(entity_name)
            if collection is None:
                return None, [
                    ConfigError(
                        code="ACCESS_UNKNOWN_ENTITY",
                        message=f"Unknown auth entity '{entity_name}' in access rule",
                        path=path,
                    )
                ]
            return IRAccessRule(principal=f"identity:{collection}"), []

        if ":" in value:
            entity_part, role_part = value.split(":", 1)
            if entity_part not in auth_entities:
                return None, [
                    ConfigError(
                        code="ACCESS_UNKNOWN_ENTITY",
                        message=f"Unknown auth entity '{entity_part}' in access rule",
                        path=path,
                    )
                ]
            collection = entity_to_collection[entity_part]
            if role_part == "*":
                return IRAccessRule(principal=f"identity:{collection}"), []
            return IRAccessRule(principal=f"identity:{collection}", required_role=role_part), []

        if not auth_entities:
            return None, [
                ConfigError(
                    code="ACCESS_NO_AUTH_ENTITY",
                    message=f"Cannot use role '{value}' without auth entities",
                    path=path,
                )
            ]
        if len(auth_entities) > 1:
            return None, [
                ConfigError(
                    code="ACCESS_AMBIGUOUS_ROLE",
                    message=f"Unscoped role '{value}' is ambiguous with multiple auth entities; use 'entity:{value}'",
                    path=path,
                )
            ]
        entity_name = next(iter(auth_entities))
        collection = entity_to_collection[entity_name]
        return IRAccessRule(principal=f"identity:{collection}", required_role=value), []

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

        if isinstance(given, dict):
            for symbol_name, symbol_value in given.items():
                if not isinstance(symbol_value, str):
                    continue
                if symbol_value.startswith("identity:"):
                    entity_name = symbol_value[len("identity:"):]
                    collection = entity_to_collection.get(entity_name)
                    if collection is None:
                        errors.append(
                            ConfigError(
                                code="ACCESS_UNKNOWN_ENTITY",
                                message=f"Unknown auth entity '{entity_name}' in access rule",
                                path=f"{path}.given.{symbol_name}",
                            )
                        )
                    else:
                        identity_symbols[symbol_name] = IRIdentityBinding(
                            entity_name=entity_name,
                            collection_name=collection,
                        )
                else:
                    parsed, doc_errors = parse_document_binding(
                        symbol_value, f"{path}.given.{symbol_name}"
                    )
                    errors.extend(doc_errors)
                    if parsed is not None:
                        document_symbols[symbol_name] = IRDocumentBinding(
                            collection=parsed[0], id_param=parsed[1]
                        )

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
            when=when_expr,
            effect=effect,
            filter=rule.get("filter"),
            write_fields=rule.get("writeFields", []),
            reason=rule.get("reason"),
        ), []
