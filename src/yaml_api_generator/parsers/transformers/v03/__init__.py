"""V0.3 YAML to IR transformation orchestrator.

v0.3 is a superset of v0.2. This transformer inherits the full v0.2 pipeline
unchanged; the v0.3-specific constructs (where binding form, service input/with,
controller bind) gain their semantics in later v0.3 issues.

v0.3 replaces the bare dotted-string ``imports`` form with an object that vendors
a package into the generated target: handlers are resolved to the vendored
package name and the source directory is copied whole (see ``vendored_imports``).
"""

from typing import Any

from ..v02 import V02Transformer
from .pagination import parse_pagination
from .vendored_imports import process_vendored_imports


class V03Transformer(V02Transformer):
    """Orchestrates v0.3 YAML to IR transformation."""

    def _process_imports(
        self, resolved: dict[str, Any]
    ) -> tuple[dict[str, str], tuple[Any, ...], tuple[str, ...]]:
        return process_vendored_imports(resolved)

    def _operation_handler_resolver(self, import_map: dict[str, str]):
        return lambda handler: (
            handler if handler is None
            else self._route._resolve_handler_path(handler, import_map)
        )

    def _make_pagination_parser(self, collections: dict[str, Any]):
        return lambda raw, collection, path: parse_pagination(
            raw, collections.get(collection), path
        )
