import copy
from typing import Any

from .entity_desugarer import EntityDesugarer
from .inheritance_desugarer import InheritanceDesugarer
from .service_desugarer import ServiceDesugarer
from .controller_desugarer import ControllerDesugarer

_REPO_DESUGARER = InheritanceDesugarer("repository")
_SVC_DESUGARER = InheritanceDesugarer("service")


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
    _REPO_DESUGARER.desugar(repositories, controllers)
    _SVC_DESUGARER.desugar(services, controllers)
    ServiceDesugarer().desugar(services, repositories, entities, defaults, auth_defaults)
    ControllerDesugarer().desugar(controllers, services)

    return config


__all__ = ["desugar_v02"]
