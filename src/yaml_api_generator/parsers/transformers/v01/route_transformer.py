"""Route and operations transformation for v0.1 specifications.

Builds routes from collection operations and access policies.
"""

from typing import Any

from yaml_api_generator.ir.api import AUTHENTICATED
from yaml_api_generator.ir import IRAccessRule, IRIdentityCollection, IROperations, IRRoute
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors
from yaml_api_generator.parsers.when_parser import parse_when_expr
from yaml_api_generator.parsers.transformers.principal_resolver import resolve_principal


class RouteTransformer:
    """Builds routes from collection operations."""

    _OPERATION_NAMES = ("list", "get", "create", "update", "replace", "delete")
    _ROUTE_MAPPING: dict[str, tuple[str, str]] = {
        "list": ("GET", "/{collection}"),
        "get": ("GET", "/{collection}/{id}"),
        "create": ("POST", "/{collection}"),
        "update": ("PATCH", "/{collection}/{id}"),
        "replace": ("PUT", "/{collection}/{id}"),
        "delete": ("DELETE", "/{collection}/{id}"),
    }

    def build_routes(
        self,
        collections_data: dict[str, Any],
        collection_names: list[str],
        collection_access_policies: dict[str, dict[str, Any]],
        identity_collections: dict[str, IRIdentityCollection],
        global_defaults: dict[str, Any],
    ) -> list[IRRoute]:
        """Build routes from collection operations.

        Args:
            collections_data: Raw collection configurations from YAML
            collection_names: List of collection names
            collection_access_policies: Access policies per collection
            identity_collections: Identity collection IR objects
            global_defaults: Global operation defaults

        Returns:
            List of route IR objects

        Raises:
            ConfigErrors: If access rule parsing fails
        """
        auth_entities = set(identity_collections.keys())
        entity_to_collection = {name: name for name in auth_entities}

        collection_operations: dict[str, IROperations] = {
            name: self._normalize_operations(global_defaults, collections_data[name].get("operations"))
            for name in collection_names
        }

        routes: list[IRRoute] = []
        errors: list[ConfigError] = []
        for name in collection_names:
            collection_routes, route_errors = self._build_collection_routes(
                name,
                collection_operations[name],
                collection_access_policies.get(name, {}),
                auth_entities,
                entity_to_collection,
            )
            routes.extend(collection_routes)
            errors.extend(route_errors)

        if errors:
            raise ConfigErrors(errors)

        for name, identity in identity_collections.items():
            if identity.has_password:
                routes.append(
                    IRRoute(
                        method="POST",
                        path=f"/{name}/login",
                        operation="login",
                        collection=name,
                        is_public=True,
                    )
                )

        return routes

    def _normalize_operations(
        self, global_defaults: dict[str, Any], collection_ops: dict[str, Any] | None
    ) -> IROperations:
        defaults = {name: True for name in self._OPERATION_NAMES}
        for name in self._OPERATION_NAMES:
            if name in global_defaults:
                defaults[name] = bool(global_defaults[name])
        if collection_ops:
            for name in self._OPERATION_NAMES:
                if name in collection_ops:
                    defaults[name] = bool(collection_ops[name])
        return IROperations(**defaults)

    def _build_collection_routes(
        self,
        collection: str,
        operations: IROperations,
        collection_access: dict[str, Any],
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> tuple[list[IRRoute], list[ConfigError]]:
        op_map = operations.__dict__
        routes: list[IRRoute] = []
        errors: list[ConfigError] = []
        for operation in self._OPERATION_NAMES:
            if not op_map[operation]:
                continue
            is_public, access_rules, access_errors = self._parse_access(
                collection_access.get(operation),
                f"collections.{collection}.access.{operation}",
                auth_entities,
                entity_to_collection,
            )
            errors.extend(access_errors)
            method, path_template = self._ROUTE_MAPPING[operation]
            routes.append(
                IRRoute(
                    method=method,
                    path=path_template.format(collection=collection, id="{id}"),
                    operation=operation,
                    collection=collection,
                    is_public=is_public,
                    access_rules=access_rules or None,
                )
            )
        return routes, errors

    def _parse_access(
        self,
        access: Any,
        path: str,
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> tuple[bool, list[IRAccessRule], list[ConfigError]]:
        if access is None:
            return True, [], []
        if isinstance(access, str):
            return self._parse_access_items([access], path, auth_entities, entity_to_collection)
        if isinstance(access, list):
            return self._parse_access_items(access, path, auth_entities, entity_to_collection)
        return True, [], []

    def _parse_access_items(
        self,
        items: list[Any],
        path: str,
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> tuple[bool, list[IRAccessRule], list[ConfigError]]:
        rules: list[IRAccessRule] = []
        errors: list[ConfigError] = []
        is_public = False
        for index, item in enumerate(items):
            principal_value, when_raw, extras = self._unpack_item(item)
            if principal_value is None:
                continue
            item_path = f"{path}[{index}]"
            resolved, resolve_errors = resolve_principal(
                principal_value, item_path, auth_entities, entity_to_collection
            )
            errors.extend(resolve_errors)
            if resolved is None:
                continue
            if resolved.is_public:
                is_public = True
                continue
            when_expr = None
            if when_raw is not None:
                when_expr, when_errors = parse_when_expr(when_raw, f"{item_path}.when")
                errors.extend(when_errors)
            if self._is_bare_authenticated(resolved, when_expr):
                continue
            rules.append(
                IRAccessRule(
                    principal=resolved.principal or AUTHENTICATED,
                    required_role=resolved.required_role,
                    when=when_expr,
                    **extras,
                )
            )
        return is_public, rules, errors

    @staticmethod
    def _is_bare_authenticated(resolved, when_expr) -> bool:
        """A plain 'authenticated' principal carries no identity, role, or constraint,
        so it adds nothing beyond requiring authentication; no rule is emitted."""
        return resolved.principal is None and resolved.required_role is None and when_expr is None

    @staticmethod
    def _unpack_item(item: Any) -> tuple[str | None, str | None, dict[str, Any]]:
        if isinstance(item, str):
            return item, None, {}
        if isinstance(item, dict):
            principal = item.get("principal")
            extras = {"reason": item.get("reason")}
            return (principal if isinstance(principal, str) else None), item.get("when"), extras
        return None, None, {}
