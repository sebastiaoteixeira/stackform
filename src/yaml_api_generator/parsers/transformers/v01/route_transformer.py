"""Route and operations transformation for v0.1 specifications.

Builds routes from collection operations and access policies.
"""

from typing import Any

from yaml_api_generator.ir import IRIdentityCollection, IROperations, IRRoute


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
        """
        collection_operations: dict[str, IROperations] = {
            name: self._normalize_operations(global_defaults, collections_data[name].get("operations"))
            for name in collection_names
        }

        routes: list[IRRoute] = []
        for name in collection_names:
            routes.extend(
                self._build_collection_routes(
                    name,
                    collection_operations[name],
                    collection_access_policies.get(name, {}),
                )
            )

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
    ) -> list[IRRoute]:
        op_map = operations.__dict__
        routes: list[IRRoute] = []
        for operation in self._OPERATION_NAMES:
            if not op_map[operation]:
                continue
            is_public = self._is_operation_public(collection_access.get(operation))
            if is_public is None:
                is_public = True
            method, path_template = self._ROUTE_MAPPING[operation]
            routes.append(
                IRRoute(
                    method=method,
                    path=path_template.format(collection=collection, id="{id}"),
                    operation=operation,
                    collection=collection,
                    is_public=is_public,
                )
            )
        return routes

    def _is_operation_public(self, access_value: Any) -> bool | None:
        if access_value is None:
            return None
        if isinstance(access_value, str):
            normalized = access_value.strip().lower()
            if normalized == "public":
                return True
            if normalized in {"authenticated", } or normalized.startswith("identity:"):
                return False
            return None
        if not isinstance(access_value, list):
            return None
        saw_rule = False
        for rule in access_value:
            if not isinstance(rule, dict):
                continue
            principal = rule.get("principal")
            if not isinstance(principal, str):
                continue
            principal_normalized = principal.strip().lower()
            principal_type = (
                "identity" if principal_normalized.startswith("identity:")
                else principal_normalized
            )
            if not principal_type:
                continue
            saw_rule = True
            if principal_type == "public":
                return True
        return False if saw_rule else None
