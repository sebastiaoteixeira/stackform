from typing import Any

from ..yaml_parser import ConfigError, ConfigErrors


CRUD_ROUTE_CONVENTIONS = {
    "list": {"method": "GET", "path": ""},
    "get": {"method": "GET", "path": "/{id}"},
    "create": {"method": "POST", "path": ""},
    "update": {"method": "PATCH", "path": "/{id}"},
    "replace": {"method": "PUT", "path": "/{id}"},
    "delete": {"method": "DELETE", "path": "/{id}"},
}

AUTH_ROUTE_CONVENTIONS = {
    "register": {"method": "POST", "path": "/register"},
    "login": {"method": "POST", "path": "/login"},
}

ALL_ROUTE_CONVENTIONS = {**CRUD_ROUTE_CONVENTIONS, **AUTH_ROUTE_CONVENTIONS}

_CONTROLLER_DEFAULTS = ("service", "access", "operations")


class ControllerDesugarer:
    """Expand every controller into explicit routes.

    Each route is layered from least to most specific: the controller
    ``access`` (public when absent), what the route exposes (the ``routes``
    entry, or for a service-bound controller the service operation and its
    method/path convention), the ``operations`` override and, for a
    service-bound controller, the ``routes`` refinement.
    ``operations.<name>: false`` drops the route.
    """

    def desugar(
        self, controllers: dict[str, Any], expanded_services: dict[str, Any]
    ) -> None:
        errors: list[ConfigError] = []
        for ctrl_name, entry in controllers.items():
            if not isinstance(entry, dict):
                continue
            try:
                entry["routes"] = self._routes(ctrl_name, entry, expanded_services)
            except ConfigErrors as error:
                errors.extend(error.errors)
            for key in _CONTROLLER_DEFAULTS:
                entry.pop(key, None)
        if errors:
            raise ConfigErrors(errors)

    def _routes(
        self, ctrl_name: str, entry: dict[str, Any], expanded_services: dict[str, Any]
    ) -> dict[str, Any]:
        routes = entry.get("routes") or {}
        overrides = entry.get("operations") or {}
        base = {"access": entry.get("access", "public")}
        if "service" in entry:
            exposed = self._exposed(ctrl_name, entry["service"], expanded_services)
            refinements = routes
        else:
            exposed, refinements = routes, {}

        errors = [
            self._unexposed(ctrl_name, section, name)
            for section, names in (("operations", overrides), ("routes", refinements))
            for name in names
            if name not in exposed
        ]
        layered = {
            name: {
                **base,
                **route,
                **(overrides.get(name) if isinstance(overrides.get(name), dict) else {}),
                **refinements.get(name, {}),
            }
            for name, route in exposed.items()
            if overrides.get(name) is not False
        }
        errors += [
            ConfigError(
                code="DESUGAR_CUSTOM_OP_MISSING_ROUTE",
                message=f"Custom operation '{name}' requires 'method' and 'path'",
                path=f"controllers.{ctrl_name}.operations.{name}",
            )
            for name, route in layered.items()
            if "method" not in route or "path" not in route
        ]
        if errors:
            raise ConfigErrors(errors)
        return layered

    def _exposed(
        self, ctrl_name: str, service_name: str, expanded_services: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Map each operation of the service group to its route convention."""
        exposed = {
            operation: {"service": svc_key, **ALL_ROUTE_CONVENTIONS.get(operation, {})}
            for svc_key in expanded_services
            if "-" in svc_key
            for operation, group in (svc_key.split("-", 1),)
            if group == service_name
        }
        if not exposed:
            raise ConfigErrors([ConfigError(
                code="DESUGAR_SERVICE_NOT_FOUND",
                message=f"No services found for service group '{service_name}'",
                path=f"controllers.{ctrl_name}.service",
            )])
        return exposed

    @staticmethod
    def _unexposed(ctrl_name: str, section: str, name: str) -> ConfigError:
        return ConfigError(
            code="DESUGAR_OPERATION_NOT_EXPOSED",
            message=f"Controller '{ctrl_name}' configures '{name}', which it does not expose",
            path=f"controllers.{ctrl_name}.{section}.{name}",
        )
