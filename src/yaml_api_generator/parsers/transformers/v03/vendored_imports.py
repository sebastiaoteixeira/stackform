"""v0.3 vendored import processing.

Under v0.3 an ``imports`` entry is an object that vendors a package into the
generated target instead of importing an author-side dotted module. Each entry
declares a source ``path`` copied whole into ``target/<package>/**``, the
``package`` name emitted code imports, and optional ``requires`` merged into the
target dependency manifest.
"""

from typing import Any

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from yaml_api_generator.ir.api import IRVendoredImport
from yaml_api_generator.parsers.yaml_parser import ConfigError


def process_vendored_imports(
    resolved: dict[str, Any],
) -> tuple[dict[str, str], tuple[IRVendoredImport, ...], tuple[str, ...]]:
    imports_data = resolved.get("imports", {})
    errors: list[ConfigError] = []
    import_map: dict[str, str] = {}
    vendored: list[IRVendoredImport] = []
    package_owner: dict[str, str] = {}

    for alias, entry in imports_data.items():
        path = f"imports.{alias}"
        if isinstance(entry, str):
            errors.append(ConfigError(
                code="IMPORT_BARE_STRING",
                message=f"Import '{alias}' uses the bare dotted-string form, which v0.3 does not accept",
                path=path,
                hint="Vendor the package with an object: { path: ./src/handlers, package: name, requires: [...] }",
            ))
            continue
        if not isinstance(entry, dict):
            errors.append(ConfigError(
                code="IMPORT_INVALID",
                message=f"Import '{alias}' must be an object with 'path' and 'package'",
                path=path,
            ))
            continue

        package = entry.get("package")
        source_path = entry.get("path")
        if not isinstance(package, str) or not package.strip():
            errors.append(ConfigError(
                code="IMPORT_INVALID",
                message=f"Import '{alias}' is missing a 'package' name",
                path=f"{path}.package",
            ))
            continue
        if not isinstance(source_path, str) or not source_path.strip():
            errors.append(ConfigError(
                code="IMPORT_INVALID",
                message=f"Import '{alias}' is missing a source 'path'",
                path=f"{path}.path",
            ))
            continue

        if package in package_owner:
            errors.append(ConfigError(
                code="IMPORT_PACKAGE_COLLISION",
                message=f"Package '{package}' is vendored by both '{package_owner[package]}' and '{alias}'",
                path=f"{path}.package",
                hint="Each vendored package name must be unique; shared local code belongs in its own imports entry",
            ))
            continue
        package_owner[package] = alias

        requires = tuple(entry.get("requires", ()) or ())
        import_map[alias] = package
        vendored.append(IRVendoredImport(package=package, path=source_path, requires=requires))

    errors.extend(_undeclared_handler_errors(resolved, import_map))

    requirements: tuple[str, ...] = ()
    if not errors:
        requirements, conflict_errors = _merge_requirements(vendored)
        errors.extend(conflict_errors)

    from yaml_api_generator.parsers.yaml_parser import ConfigErrors
    if errors:
        raise ConfigErrors(errors)

    return import_map, tuple(vendored), requirements


def _undeclared_handler_errors(
    resolved: dict[str, Any], import_map: dict[str, str]
) -> list[ConfigError]:
    errors: list[ConfigError] = []
    for handler, path in _handler_sites(resolved):
        alias = handler.split(".", 1)[0]
        if alias not in import_map:
            errors.append(ConfigError(
                code="IMPORT_UNDECLARED_PACKAGE",
                message=f"Handler '{handler}' references package '{alias}', which no imports entry vendors",
                path=path,
                hint=f"Add an imports entry aliased '{alias}' that vendors the package",
            ))
    return errors


def _handler_sites(resolved: dict[str, Any]):
    for name, cfg in resolved.get("services", {}).items():
        if isinstance(cfg, dict):
            handler = cfg.get("handler")
            if isinstance(handler, str) and "." in handler:
                yield handler, f"services.{name}.handler"
    for repo_name, repo_cfg in resolved.get("repositories", {}).items():
        if not isinstance(repo_cfg, dict):
            continue
        for op_name, op_cfg in repo_cfg.get("operations", {}).items():
            if isinstance(op_cfg, dict):
                handler = op_cfg.get("handler")
                if isinstance(handler, str) and "." in handler:
                    yield handler, f"repositories.{repo_name}.operations.{op_name}.handler"


def _merge_requirements(
    vendored: list[IRVendoredImport],
) -> tuple[tuple[str, ...], list[ConfigError]]:
    by_name: dict[str, list[Requirement]] = {}
    for vi in vendored:
        for raw in vi.requires:
            req = Requirement(raw)
            by_name.setdefault(req.name, []).append(req)

    errors: list[ConfigError] = []
    merged: list[str] = []
    for name in sorted(by_name):
        reqs = by_name[name]
        combined = SpecifierSet()
        for req in reqs:
            combined &= req.specifier
        if not _is_satisfiable(combined):
            pins = ", ".join(sorted(str(r) for r in reqs))
            errors.append(ConfigError(
                code="IMPORT_REQUIRES_CONFLICT",
                message=f"Vendored requirements for '{name}' are incompatible: {pins}",
                path="imports",
            ))
            continue
        merged.append(f"{name}{combined}" if str(combined) else name)
    return tuple(merged), errors


def _is_satisfiable(specifier: SpecifierSet) -> bool:
    if not str(specifier):
        return True
    candidates: set[Version] = set()
    for spec in specifier:
        base = Version(spec.version)
        release = base.release
        candidates.add(base)
        candidates.add(Version(".".join(map(str, release)) + ".post0"))
        if release[-1] > 0:
            lowered = release[:-1] + (release[-1] - 1,)
            candidates.add(Version(".".join(map(str, lowered))))
        candidates.add(Version(".".join(map(str, release + (1,)))))
    return any(specifier.contains(c, prereleases=True) for c in candidates)
