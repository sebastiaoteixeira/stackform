"""v0.3 vendored import processing.

Under v0.3 an ``imports`` entry is an object that vendors a package into the
generated target instead of importing an author-side dotted module. Each entry
declares a source ``path`` copied whole into ``target/<package>/**``, the
``package`` name emitted code imports, and optional ``requires`` merged into the
target dependency manifest.

A source is resolved against the directory holding the spec and must stay inside
it, so an absolute or escaping ``path`` is rejected instead of reading the host
filesystem. It must be a regular package, because the emitted ``import
<package>`` has to expose the handler as an attribute. A symlink inside a
vendored tree whose target leaves that tree is rejected as well: links that stay
inside are preserved as links when the tree is copied, so nothing outside the
tree is ever materialised into the target.

Declaring ``imports`` opts the whole spec into vendoring: every handler must
then name a vendored package. A v0.3 spec without an ``imports`` block keeps the
v0.2 handler semantics unchanged, where a dotted handler is emitted verbatim and
imported from the target environment.

``requires`` are merged per library and per environment marker. Extras are
unioned, markers and direct URLs are carried through verbatim, and specifiers
are conjoined. A conflict is only reported where it is decidable: a set that
pins exact versions is unsatisfiable exactly when it contains none of its own
pins, and a library constrained by both a direct URL and a version cannot be
expressed as one requirement. Every other set is emitted as the conjunction of
the declared specifiers and left to the target installer to resolve; the
generator does not decide PEP 440 satisfiability in general.
"""

from pathlib import Path
from typing import Any, Iterator

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from yaml_api_generator.ir.api import IRVendoredImport
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors


def process_vendored_imports(
    resolved: dict[str, Any], spec_dir: Path
) -> tuple[dict[str, str], tuple[IRVendoredImport, ...], tuple[str, ...]]:
    entries = resolved.get("imports") or {}
    if not entries:
        return {}, (), ()

    errors: list[ConfigError] = []
    import_map: dict[str, str] = {}
    vendored: list[IRVendoredImport] = []
    package_owner: dict[str, str] = {}

    for alias, entry in entries.items():
        path = f"imports.{alias}"
        package = entry["package"]
        if package in package_owner:
            errors.append(ConfigError(
                code="IMPORT_PACKAGE_COLLISION",
                message=f"Package '{package}' is vendored by both '{package_owner[package]}' and '{alias}'",
                path=f"{path}.package",
                hint="Each vendored package name must be unique; shared local code belongs in its own imports entry",
            ))
            continue

        source = _resolve_source(alias, entry["path"], spec_dir, errors)
        if source is None:
            continue

        package_owner[package] = alias
        import_map[alias] = package
        vendored.append(IRVendoredImport(
            alias=alias,
            package=package,
            source=source,
            requires=tuple(entry.get("requires") or ()),
        ))

    requirements: tuple[str, ...] = ()
    if not errors:
        errors = _undeclared_handler_errors(resolved, import_map)
    if not errors:
        requirements, errors = _merge_requirements(vendored)

    if errors:
        raise ConfigErrors(errors)

    return import_map, tuple(vendored), requirements


def _resolve_source(
    alias: str, raw_path: str, spec_dir: Path, errors: list[ConfigError]
) -> Path | None:
    path = f"imports.{alias}.path"
    root = spec_dir.resolve()
    source = (root / raw_path).resolve()

    if not source.is_relative_to(root):
        errors.append(ConfigError(
            code="IMPORT_SOURCE_OUTSIDE_SPEC",
            message=f"Import '{alias}' vendors '{raw_path}', which resolves outside the spec directory",
            path=path,
            hint="A vendored source must live inside the directory holding the spec",
        ))
        return None

    if not source.is_dir():
        errors.append(ConfigError(
            code="IMPORT_SOURCE_MISSING",
            message=f"Import '{alias}' vendors '{raw_path}', which is not an existing directory",
            path=path,
        ))
        return None

    if not (source / "__init__.py").is_file():
        errors.append(ConfigError(
            code="IMPORT_SOURCE_NOT_PACKAGE",
            message=f"Import '{alias}' vendors '{raw_path}', which has no __init__.py",
            path=path,
            hint="A vendored source must be a regular Python package so the emitted import exposes its handlers",
        ))
        return None

    escaping = next(_escaping_symlinks(source), None)
    if escaping is not None:
        errors.append(ConfigError(
            code="IMPORT_SOURCE_ESCAPING_SYMLINK",
            message=(
                f"Import '{alias}' vendors a tree containing '{escaping.relative_to(source)}', "
                "a symlink pointing outside it"
            ),
            path=path,
            hint="Vendoring copies the tree as-is; move the target inside the tree or drop the link",
        ))
        return None

    return source


def _escaping_symlinks(source: Path) -> Iterator[Path]:
    for entry in source.rglob("*"):
        if entry.is_symlink() and not entry.resolve().is_relative_to(source):
            yield entry


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
        if isinstance(cfg, dict) and isinstance(cfg.get("handler"), str):
            yield cfg["handler"], f"services.{name}.handler"
    for repo_name, repo_cfg in resolved.get("repositories", {}).items():
        if not isinstance(repo_cfg, dict):
            continue
        for op_name, op_cfg in repo_cfg.get("operations", {}).items():
            if isinstance(op_cfg, dict) and isinstance(op_cfg.get("handler"), str):
                yield op_cfg["handler"], f"repositories.{repo_name}.operations.{op_name}.handler"


def _merge_requirements(
    vendored: list[IRVendoredImport],
) -> tuple[tuple[str, ...], list[ConfigError]]:
    groups: dict[tuple[str, str], list[Requirement]] = {}
    errors: list[ConfigError] = []

    for vi in vendored:
        for raw in vi.requires:
            try:
                requirement = Requirement(raw)
            except InvalidRequirement as invalid:
                errors.append(ConfigError(
                    code="IMPORT_REQUIRES_INVALID",
                    message=(
                        f"Package '{vi.package}' requires '{raw}', which is not a valid "
                        f"dependency specifier: {invalid}"
                    ),
                    path="imports",
                ))
                continue
            key = (canonicalize_name(requirement.name), str(requirement.marker or ""))
            groups.setdefault(key, []).append(requirement)

    if errors:
        return (), errors

    merged: list[str] = []
    for (name, marker), requirements in sorted(groups.items()):
        outcome = _merge_group(name, marker, requirements)
        if isinstance(outcome, ConfigError):
            errors.append(outcome)
        else:
            merged.append(outcome)
    return tuple(merged), errors


def _merge_group(
    name: str, marker: str, requirements: list[Requirement]
) -> str | ConfigError:
    declared = ", ".join(sorted(str(requirement) for requirement in requirements))
    urls = {requirement.url for requirement in requirements if requirement.url}
    specifier = SpecifierSet()
    for requirement in requirements:
        specifier &= requirement.specifier

    if len(urls) > 1 or (urls and specifier):
        return ConfigError(
            code="IMPORT_REQUIRES_CONFLICT",
            message=f"Vendored requirements for '{name}' cannot be merged into one specifier: {declared}",
            path="imports",
            hint="A library pinned to a direct URL cannot also carry a version specifier or a second URL",
        )

    pins = {spec.version for spec in specifier if spec.operator == "==" and "*" not in spec.version}
    if pins and not any(specifier.contains(pin, prereleases=True) for pin in pins):
        return ConfigError(
            code="IMPORT_REQUIRES_CONFLICT",
            message=f"Vendored requirements for '{name}' are jointly unsatisfiable: {declared}",
            path="imports",
        )

    extras = sorted(set().union(*(requirement.extras for requirement in requirements)))
    rendered = name + (f"[{','.join(extras)}]" if extras else "")
    rendered += f" @ {urls.pop()}" if urls else str(specifier)
    return rendered + (f"; {marker}" if marker else "")
