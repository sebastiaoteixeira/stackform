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

    _desugar_repositories(repositories, controllers)

    # Resolve service inheritance before expansion so abstract entries and
    # base_classes are computed on the minified service dict.
    svc_base_classes = _resolve_service_inheritance(services, controllers)

    service_desugarer = ServiceDesugarer()
    service_desugarer.desugar(services, repositories, entities, defaults, auth_defaults)

    # Propagate base_classes to all flat entries that came from a concrete minified svc.
    _attach_service_base_classes(services, svc_base_classes)

    ControllerDesugarer().desugar(controllers, services)

    return config


def _desugar_repositories(repositories: dict[str, Any], controllers: dict[str, Any]) -> None:
    """Validate repo inheritance, attach base_classes, and remove abstract repos."""
    base_classes = _REPO_DESUGARER.resolve_base_classes(repositories)
    _REPO_DESUGARER.validate_not_bound(
        repositories, controllers, "repository",
        error_code="DESUGAR_ABSTRACT_REPOSITORY_BOUND",
    )
    for name, chain in base_classes.items():
        if isinstance(repositories.get(name), dict):
            repositories[name]["_base_classes"] = list(chain)
    _REPO_DESUGARER.remove_abstract(repositories)


def _resolve_service_inheritance(
    services: dict[str, Any], controllers: dict[str, Any]
) -> dict[str, tuple[str, ...]]:
    """Validate service inheritance and return base_class chains keyed by repo name."""
    base_classes_by_svc = _SVC_DESUGARER.resolve_base_classes(services)
    _SVC_DESUGARER.validate_not_bound(
        services, controllers, "service",
        error_code="DESUGAR_ABSTRACT_SERVICE_BOUND",
    )
    # Re-key by repository name so _attach_service_base_classes can match flat entries.
    base_classes_by_repo: dict[str, tuple[str, ...]] = {}
    for svc_name, chain in base_classes_by_svc.items():
        cfg = services.get(svc_name)
        repo = cfg.get("repository", svc_name) if isinstance(cfg, dict) else svc_name
        base_classes_by_repo[repo] = chain

    _SVC_DESUGARER.remove_abstract(services)
    return base_classes_by_repo


def _attach_service_base_classes(
    services: dict[str, Any], svc_base_classes: dict[str, tuple[str, ...]]
) -> None:
    """Stamp _base_classes onto each expanded flat service that originated from a named svc.

    The flat key format is ``{op}-{svc_name}``, e.g. ``list-posts``.
    """
    for cfg in services.values():
        if not isinstance(cfg, dict):
            continue
        repo = cfg.get("repository")
        if repo and repo in svc_base_classes:
            cfg["_base_classes"] = list(svc_base_classes[repo])


__all__ = ["desugar_v02"]
