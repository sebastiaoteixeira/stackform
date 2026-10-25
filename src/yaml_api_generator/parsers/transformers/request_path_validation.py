"""Cross-checks request.path.<name> references against route path templates.

A ``when`` may read ``req.path.<name>`` only when ``{name}`` appears in the
route's composed path template. The template materialises during desugaring, so
this validator runs post-desugar (mirroring ``validate_spec_paths``):

- REQUEST_PATH_PARAM_NOT_DECLARED: a request.path.<name> reference whose
  ``{name}`` is absent from the route's path.
"""

import re
from typing import Any

from yaml_api_generator.ir.when import field_refs
from yaml_api_generator.parsers.when_parser import (
    parse_request_binding,
    parse_when_list,
)
from yaml_api_generator.parsers.yaml_parser import ConfigError

_PARAM_TOKEN = re.compile(r"\{([^/{}]+)\}")

# The field-path prefix that leads from a symbol to the path parameters of the part it binds
_PATH_PREFIX = {None: ("path",), "path": ()}


def _path_symbols(given: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Each symbol bound to the request's path parameters, with its path prefix."""
    symbols: dict[str, tuple[str, ...]] = {}
    for name, value in given.items():
        if not isinstance(value, str) or not (
            value == "request" or value.startswith(("request.", "request:"))
        ):
            continue
        parsed, errors = parse_request_binding(value, "")
        if errors or parsed is None:
            continue
        part, _, _ = parsed
        if part in _PATH_PREFIX:
            symbols[name] = _PATH_PREFIX[part]
    return symbols


def _check_rule(
    rule: dict[str, Any], tokens: set[str], path: str, errors: list[ConfigError]
) -> None:
    given = rule.get("given") or {}
    when_raw = rule.get("when")
    if not isinstance(given, dict) or when_raw is None:
        return
    path_symbols = _path_symbols(given)
    if not path_symbols:
        return
    expr, when_errors = parse_when_list(when_raw, f"{path}.when")
    if when_errors or expr is None:
        return
    for ref in field_refs(expr):
        prefix = path_symbols.get(ref.root)
        if prefix is None or len(ref.path) <= len(prefix) or ref.path[:len(prefix)] != prefix:
            continue
        name = ref.path[len(prefix)]
        if name not in tokens:
            errors.append(ConfigError(
                code="REQUEST_PATH_PARAM_NOT_DECLARED",
                message=f"request.path.{name} is not a parameter of this route",
                path=f"{path}.when",
                hint=f"Declare {{{name}}} in the route path or fix the reference",
            ))


def validate_spec_request_paths(spec: dict[str, Any]) -> list[ConfigError]:
    errors: list[ConfigError] = []
    for ctrl_name, controller in (spec.get("controllers") or {}).items():
        if not isinstance(controller, dict):
            continue
        base = controller.get("base_path", "")
        for route_name, route in (controller.get("routes") or {}).items():
            if not isinstance(route, dict):
                continue
            tokens = set(_PARAM_TOKEN.findall(f"{base}{route.get('path', '')}"))
            access = route.get("access")
            if not isinstance(access, list):
                continue
            for index, item in enumerate(access):
                if isinstance(item, dict):
                    _check_rule(
                        item, tokens,
                        f"controllers.{ctrl_name}.routes.{route_name}.access[{index}]",
                        errors,
                    )
    return errors
