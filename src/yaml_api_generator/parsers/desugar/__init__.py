import copy
from typing import Any

from .entity_desugarer import EntityDesugarer
from .service_desugarer import ServiceDesugarer
from .controller_desugarer import ControllerDesugarer


def desugar_v02(config: dict[str, Any]) -> dict[str, Any]:
    """
    Desugar v02 config: expand shorthand syntax to explicit definitions.

    Processes:
    1. Entities: resolve inheritance, remove abstract entities
    2. Services: expand minified services into explicit operations
    3. Repositories: (placeholder, operations preserved for IR building)
    4. Controllers: expand service references into explicit routes

    Args:
        config: Raw v02 config dict

    Returns:
        Desugared config (same object, modified in-place)

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

    entity_desugarer = EntityDesugarer()
    entity_desugarer.desugar(entities, repositories)

    service_desugarer = ServiceDesugarer()
    expanded_services = service_desugarer.desugar(
        services, repositories, entities, defaults, auth_defaults
    )

    _desugar_repositories(repositories)

    controller_desugarer = ControllerDesugarer()
    controller_desugarer.desugar(controllers, expanded_services)

    return config


def _desugar_repositories(repositories: dict[str, Any]) -> None:
    """
    Placeholder: operations dict must survive to transformer for IRRepository building.

    No actual desugaring needed - repository operations are consumed later.
    """
    pass


__all__ = ["desugar_v02"]
