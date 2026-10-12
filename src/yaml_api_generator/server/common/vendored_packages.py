"""Make v0.3 vendored handler packages importable by the development server.

A generated target imports a vendored package by name because its source tree
was copied next to the generated code. The development server runs against the
spec in place, so the same package name is bound to the declared source
directory through a meta path finder, which gives ``stackform run`` the import
graph the generated target has.
"""

import sys
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from importlib.util import spec_from_file_location
from pathlib import Path
from typing import Any, Iterable

from yaml_api_generator.ir.api import IRVendoredImport


class VendoredPackageFinder(MetaPathFinder):
    """Binds declared vendored package names to their spec-side sources."""

    def __init__(self, sources: dict[str, Path]) -> None:
        self._sources = sources

    def find_spec(
        self, fullname: str, path: Any = None, target: Any = None
    ) -> ModuleSpec | None:
        source = self._sources.get(fullname)
        if source is None:
            return None
        return spec_from_file_location(
            fullname,
            source / "__init__.py",
            submodule_search_locations=[str(source)],
        )


def install_vendored_packages(vendored_imports: Iterable[IRVendoredImport]) -> None:
    sources = {vi.package: vi.source for vi in vendored_imports}
    if not sources:
        return

    sys.meta_path[:] = [
        finder for finder in sys.meta_path
        if not isinstance(finder, VendoredPackageFinder)
    ]
    for name in [n for n in sys.modules if n.split(".", 1)[0] in sources]:
        del sys.modules[name]
    sys.meta_path.insert(0, VendoredPackageFinder(sources))
