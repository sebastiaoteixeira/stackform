import copy
from typing import Any

from .entity_desugarer import EntityDesugarer
from .inheritance_desugarer import InheritanceDesugarer
from .service_desugarer import ServiceDesugarer
from .controller_desugarer import ControllerDesugarer

_REPO_DESUGARER = InheritanceDesugarer("repository")
_SVC_DESUGARER = InheritanceDesugarer("service")


def _bindings(**sections: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        f"{section}.{name}": cfg
        for section, entries in sections.items()
        for name, cfg in entries.items() if isinstance(cfg, dict)
    }


def desugar_v02(config: dict[str, Any]) -> dict[str, Any]:
    """Desugar v02 config: expand shorthand syntax to explicit definitions.

    Processes entities, services, repositories, and controllers in dependency order.

    Args:
        config: Raw v02 config dict

    Returns:
        Desugared config (modified deep-copy)

    Raises:
        ConfigErrors: If desugaring validation fails
    """
    config = copy.deepcopy(config)

    api_ops = config.get("api", {}).get("operations", {})
    defaults = api_ops.get("defaults", {})
    auth_defaults = api_ops.pop("auth", {})
    repositories = config.get("repositories", {})
    entities = config.get("entities", {})
    services = config.get("services", {})
    controllers = config.get("controllers", {})

    EntityDesugarer().desugar(entities, repositories)
    routes = {
        f"controllers.{name}.routes.{route_name}": route
        for name, ctrl in controllers.items() if isinstance(ctrl, dict)
        for route_name, route in (ctrl.get("routes") or {}).items()
    }
    _REPO_DESUGARER.desugar(repositories, _bindings(controllers=controllers, services=services))
    _SVC_DESUGARER.desugar(services, {**_bindings(controllers=controllers), **routes})
    ServiceDesugarer().desugar(services, repositories, entities, defaults, auth_defaults)
    ControllerDesugarer().desugar(controllers, services)

    return config


__all__ = ["desugar_v02"]
