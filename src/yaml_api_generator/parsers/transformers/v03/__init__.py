"""V0.3 YAML to IR transformation orchestrator.

v0.3 is a superset of v0.2 and enables the version-specific where-binding and
service input/forwarding grammar.

v0.3 also replaces the bare dotted-string ``imports`` form with an object that
vendors a package into the generated target: handlers are resolved to the
vendored package name and the source directory is copied whole (see
``vendored_imports``).
"""

from pathlib import Path
from typing import Any

from ..v02 import V02Transformer
from ..v02.access_transformer import AccessTransformer
from ..v02.route_transformer import RouteTransformer
from .pagination import parse_pagination
from .vendored_imports import process_vendored_imports


class V03Transformer(V02Transformer):
    """Orchestrates v0.3 YAML to IR transformation."""

    def __init__(self, spec_dir: Path) -> None:
        super().__init__()
        self._spec_dir = spec_dir
        self._access = AccessTransformer(allow_where=True)
        self._route = RouteTransformer(self._access)

    def _process_imports(
        self, resolved: dict[str, Any]
    ) -> tuple[dict[str, str], tuple[Any, ...], tuple[str, ...]]:
        return process_vendored_imports(resolved, self._spec_dir)

    def _operation_handler_resolver(self, import_map: dict[str, str]):
        return lambda handler: (
            handler if handler is None
            else self._route._resolve_handler_path(handler, import_map)
        )

    def _make_pagination_parser(self, collections: dict[str, Any]):
        return lambda raw, collection, path: parse_pagination(
            raw, collections.get(collection), path
        )
