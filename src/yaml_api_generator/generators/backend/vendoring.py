"""Copy vendored handler packages into the generated backend.

Each v0.3 vendored import declares a source directory copied whole into
``backend/<package>``, so local helper modules travel with the handler and the
emitted ``import <package>`` resolves against the target tree.

The copy preserves symlinks instead of following them, so a link can never
materialise content from outside the vendored tree into the target, and it
refuses a destination that already holds generated code, so a vendored package
can never shadow a generated module. Copies left by an earlier build of the same
spec are cleared before generation, which keeps rebuilding into one output
directory idempotent.
"""

import shutil
from pathlib import Path
from typing import Iterable

from yaml_api_generator.ir.api import IRVendoredImport
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors


def clear_vendored(
    vendored_imports: Iterable[IRVendoredImport], backend_dir: Path
) -> None:
    for vi in vendored_imports:
        shutil.rmtree(Path(backend_dir) / vi.package, ignore_errors=True)


def vendor_packages(
    vendored_imports: Iterable[IRVendoredImport], backend_dir: Path
) -> None:
    errors: list[ConfigError] = []
    for vi in vendored_imports:
        destination = Path(backend_dir) / vi.package
        if destination.exists():
            errors.append(ConfigError(
                code="IMPORT_PACKAGE_SHADOWS_TARGET",
                message=(
                    f"Import '{vi.alias}' vendors package '{vi.package}', which the "
                    f"{destination.name!r} module of the generated backend already occupies"
                ),
                path=f"imports.{vi.alias}.package",
                hint="Rename the vendored package so it does not shadow generated code",
            ))
            continue
        shutil.copytree(vi.source, destination, symlinks=True)
    if errors:
        raise ConfigErrors(errors)
