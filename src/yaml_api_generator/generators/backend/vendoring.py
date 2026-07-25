"""Copy vendored handler packages into the generated backend.

Each v0.3 vendored import declares a source ``path`` copied whole into
``backend/<package>``, so local helper modules travel with the handler and the
emitted ``import <package>`` resolves against the target tree.
"""

import shutil
from pathlib import Path
from typing import Iterable

from yaml_api_generator.ir.api import IRVendoredImport


def vendor_packages(
    vendored_imports: Iterable[IRVendoredImport],
    source_root: Path,
    backend_dir: Path,
) -> None:
    for vi in vendored_imports:
        source = (Path(source_root) / vi.path).resolve()
        shutil.copytree(source, Path(backend_dir) / vi.package, dirs_exist_ok=True)
