from typing import Any

from ..yaml_parser import ConfigError, ConfigErrors


CRUD_ROUTE_CONVENTIONS = {
    "list": ("GET", ""),
    "get": ("GET", "/{id}"),
    "create": ("POST", ""),
    "update": ("PATCH", "/{id}"),
    "replace": ("PUT", "/{id}"),
    "delete": ("DELETE", "/{id}"),
}

AUTH_ROUTE_CONVENTIONS = {
    "register": ("POST", "/register"),
    "login": ("POST", "/login"),
}

ALL_ROUTE_CONVENTIONS = {**CRUD_ROUTE_CONVENTIONS, **AUTH_ROUTE_CONVENTIONS}


class ControllerDesugarer:
    """
    Handles controller desugaring: expand service references into explicit routes.

    Responsibilities:
    - Detect minified controller definitions (with "service" key)
    - Match service operations to controller
    - Apply route conventions (method + path for CRUD/auth ops)
    - Resolve access control per operation
    - Generate routes dict
    """

    def desugar(
        self, controllers: dict[str, Any], expanded_services: dict[str, Any]
    ) -> None:
        """
        Desugar controllers in-place: expand service references into routes.

        Args:
            controllers: Controller definitions to desugar
            expanded_services: Expanded service definitions (post-service desugaring)

        Raises:
            ConfigErrors: If validation fails
        """
        errors: list[ConfigError] = []

        for ctrl_name, entry in list(controllers.items()):
            if not isinstance(entry, dict):
                continue

            if not self._is_minified_controller(entry):
                continue

            try:
                self._expand_minified_controller(
                    ctrl_name, entry, expanded_services
                )
            except ConfigError as e:
                errors.append(e)

        if errors:
            raise ConfigErrors(errors)

    def _is_minified_controller(self, entry: dict[str, Any]) -> bool:
        """Check if controller entry is minified (needs expansion)."""
        return "service" in entry

    def _expand_minified_controller(
        self,
        ctrl_name: str,
        entry: dict[str, Any],
        expanded_services: dict[str, Any],
    ) -> None:
        """Expand a minified controller into explicit route definitions."""
        service_name = entry["service"]
        base_access = entry.get("access", "public")
        ops_overrides = entry.get("operations", {})
        route_overrides = entry.get("routes", {})

        matching_services = self._find_matching_services(
            service_name, expanded_services
        )

        if not matching_services:
            raise ConfigError(
                code="DESUGAR_SERVICE_NOT_FOUND",
                message=f"No services found for service group '{service_name}'",
                path=f"controllers.{ctrl_name}.service",
            )

        routes = self._build_routes(
            ctrl_name, matching_services, base_access, ops_overrides, route_overrides
        )

        entry.pop("service", None)
        entry.pop("access", None)
        entry.pop("operations", None)
        entry.pop("routes", None)
        entry["routes"] = routes

    def _find_matching_services(
        self, service_name: str, expanded_services: dict[str, Any]
    ) -> dict[str, str]:
        """
        Find expanded service keys matching service_name.

        Returns dict: operation -> service_key (e.g., "list" -> "list-users")
        """
        matching_services: dict[str, str] = {}
        for svc_key in expanded_services.keys():
            if "-" not in svc_key:
                continue
            op_part, svc_part = svc_key.split("-", 1)
            if svc_part == service_name:
                matching_services[op_part] = svc_key
        return matching_services

    def _build_routes(
        self,
        ctrl_name: str,
        matching_services: dict[str, str],
        base_access: str,
        ops_overrides: dict[str, Any],
        route_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build routes dict from matching services and overrides."""
        routes: dict[str, Any] = {}
        errors: list[ConfigError] = []
        effective_route_overrides = route_overrides or {}

        for op_name, svc_key in matching_services.items():
            op_override = ops_overrides.get(op_name)
            if op_override is False:
                continue

            route_override = effective_route_overrides.get(op_name)

            try:
                route = self._build_single_route(
                    ctrl_name, op_name, svc_key, base_access, op_override, route_override
                )
                routes[op_name] = route
            except ConfigError as e:
                errors.append(e)

        if errors:
            raise ConfigErrors(errors)

        return routes

    def _build_single_route(
        self,
        ctrl_name: str,
        op_name: str,
        svc_key: str,
        base_access: str,
        op_override: Any,
        route_override: Any = None,
    ) -> dict[str, Any]:
        """Build a single route definition."""
        if op_name in ALL_ROUTE_CONVENTIONS:
            method, path = ALL_ROUTE_CONVENTIONS[op_name]
        else:
            if (
                not isinstance(op_override, dict)
                or "method" not in op_override
                or "path" not in op_override
            ):
                raise ConfigError(
                    code="DESUGAR_CUSTOM_OP_MISSING_ROUTE",
                    message=f"Custom operation '{op_name}' requires 'method' and 'path'",
                    path=f"controllers.{ctrl_name}.operations.{op_name}",
                )
            method = op_override["method"]
            path = op_override["path"]

        access = base_access
        if isinstance(route_override, dict) and "access" in route_override:
            access = route_override["access"]
        elif isinstance(op_override, dict) and "access" in op_override:
            access = op_override["access"]

        route = {
            "service": svc_key,
            "method": method,
            "path": path,
            "access": access,
        }
        pagination = None
        if isinstance(op_override, dict):
            pagination = op_override.get("pagination")
        if isinstance(route_override, dict) and "pagination" in route_override:
            pagination = route_override["pagination"]
        if pagination is not None:
            route["pagination"] = pagination
        return route
