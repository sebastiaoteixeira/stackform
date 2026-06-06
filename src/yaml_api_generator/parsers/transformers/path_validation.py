"""Route-path uniqueness and base_path well-formedness for a v0.2 spec.

The generator composes every route as ``api.basePath`` (optionally suffixed with
``api.version``) + ``controller.base_path`` + ``route.path`` and registers it
verbatim with the web framework. The JSON schema validates each path string in
isolation, so three classes of mistake survive it and only surface as runtime
failures or silent misbehaviour:

- two routes resolving to the same METHOD plus full path collide: the framework
  keeps whichever it registered last and the other is silently dropped. This is
  the concrete form controller shadowing takes -- two controllers may share a
  ``base_path`` so long as their composed routes stay disjoint, but the moment a
  full path repeats the later route becomes unreachable.
- a ``base_path`` carrying its own path-param token (``/tenants/{id}``) composes
  with the per-item ``/{id}`` suffix into a path with two ``{id}`` segments,
  which raises a Starlette ``Duplicated param name`` ValueError at import.

This validator runs on the desugared spec (mirroring the other semantic
validators but after desugar, since minified controllers only materialise their
``routes`` during desugaring), so it sees the same routes the transformer emits.
"""

import re
from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError

# A path segment is either a literal (letters, digits, -, _, .) or a single
# ``{name}`` capture. base_path must be empty (the default) or a sequence of
# literal segments only; param tokens belong on the per-route path, never the
# controller prefix.
_PARAM_TOKEN = re.compile(r"\{[^/{}]+\}")
_BASE_PATH = re.compile(r"^(/[A-Za-z0-9._-]+)+$")


def _api_prefix(api: dict[str, Any]) -> str:
    base = api.get("basePath", "/api") if isinstance(api, dict) else "/api"
    version = api.get("version", "") if isinstance(api, dict) else ""
    return f"{base}/{version}" if version else base


def _check_base_path(value: str, path: str, errors: list[ConfigError]) -> bool:
    """Validate a controller base_path; return False if it is unusable."""
    if value == "":
        return True
    if _PARAM_TOKEN.search(value):
        errors.append(ConfigError(
            code="CONTROLLER_BASE_PATH_INVALID",
            message=f"base_path '{value}' contains a path parameter token",
            path=path,
            hint="Keep parameters on the route path; base_path must be literal segments",
        ))
        return False
    if not _BASE_PATH.match(value):
        errors.append(ConfigError(
            code="CONTROLLER_BASE_PATH_INVALID",
            message=f"base_path '{value}' is malformed",
            path=path,
            hint="Use a leading slash and literal segments, e.g. /my-entity",
        ))
        return False
    return True


def validate_spec_paths(spec: dict[str, Any]) -> list[ConfigError]:
    """Validate base_path well-formedness and full-path/base_path uniqueness."""
    errors: list[ConfigError] = []
    controllers = spec.get("controllers") or {}
    prefix = _api_prefix(spec.get("api") or {})

    seen_routes: dict[tuple[str, str], str] = {}

    for ctrl_name, controller in controllers.items():
        if not isinstance(controller, dict):
            continue
        base = controller.get("base_path", "")
        if not _check_base_path(base, f"controllers.{ctrl_name}.base_path", errors):
            continue

        for route_name, route in (controller.get("routes") or {}).items():
            if not isinstance(route, dict):
                continue
            method = str(route.get("method", "")).upper()
            full_path = f"{prefix}{base}{route.get('path', '')}"
            key = (method, full_path)
            prior_route = seen_routes.get(key)
            if prior_route is not None:
                errors.append(ConfigError(
                    code="ROUTE_PATH_DUPLICATE",
                    message=(
                        f"{method} {full_path} is already defined by '{prior_route}'"
                    ),
                    path=f"controllers.{ctrl_name}.routes.{route_name}",
                    hint="Two routes must not share the same method and full path",
                ))
            else:
                seen_routes[key] = f"controllers.{ctrl_name}.routes.{route_name}"

    return errors
