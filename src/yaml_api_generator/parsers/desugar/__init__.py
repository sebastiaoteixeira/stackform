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
    auth_defaults = api_ops.get("auth", {})
    repositories = config.get("repositories", {})
    entities = config.get("entities", {})
    services = config.get("services", {})
    controllers = config.get("controllers", {})

    EntityDesugarer().desugar(entities, repositories)

    _desugar_repositories(repositories, controllers)

    # Resolve service inheritance before expansion so abstract entries and the
    # inherited base are computed on the minified service dict.
    svc_inherits = _resolve_service_inheritance(services, controllers)

    service_desugarer = ServiceDesugarer()
    service_desugarer.desugar(services, repositories, entities, defaults, auth_defaults)

    # Propagate the inherited base to all flat entries from a concrete minified svc.
    _attach_service_inherits(services, svc_inherits)

    ControllerDesugarer().desugar(controllers, services)

    return config


def _desugar_repositories(repositories: dict[str, Any], controllers: dict[str, Any]) -> None:
    """Validate repo inheritance, stamp the inherited base, drop empty abstracts.

    Abstract repositories that declare operations are kept: they are rendered
    as generated base classes that concrete repositories inherit.
    """
    inherits = _REPO_DESUGARER.resolve(repositories)
    _REPO_DESUGARER.validate_not_bound(
        repositories, controllers, "repository",
        error_code="DESUGAR_ABSTRACT_REPOSITORY_BOUND",
    )
    for name, base in inherits.items():
        cfg = repositories.get(name)
        if isinstance(cfg, dict):
            cfg["_inherits"] = base
    _REPO_DESUGARER.remove_abstract(repositories)


def _resolve_service_inheritance(
    services: dict[str, Any], controllers: dict[str, Any]
) -> dict[str, str | None]:
    """Validate service inheritance and return the inherited base keyed by repo name."""
    inherits = _SVC_DESUGARER.resolve(services)
    _SVC_DESUGARER.validate_not_bound(
        services, controllers, "service",
        error_code="DESUGAR_ABSTRACT_SERVICE_BOUND",
    )
    # Re-key by repository name so _attach_service_inherits can match flat entries.
    inherits_by_repo: dict[str, str | None] = {}
    for svc_name, base in inherits.items():
        cfg = services.get(svc_name)
        repo = cfg.get("repository", svc_name) if isinstance(cfg, dict) else svc_name
        inherits_by_repo[repo] = base

    _SVC_DESUGARER.remove_abstract(services)
    return inherits_by_repo


def _attach_service_inherits(
    services: dict[str, Any], svc_inherits: dict[str, str | None]
) -> None:
    """Stamp _inherits onto each expanded flat service that originated from a named svc.

    The flat key format is ``{op}-{svc_name}``, e.g. ``list-posts``.
    """
    for cfg in services.values():
        if not isinstance(cfg, dict):
            continue
        repo = cfg.get("repository")
        if repo and repo in svc_inherits:
            cfg["_inherits"] = svc_inherits[repo]


__all__ = ["desugar_v02"]
