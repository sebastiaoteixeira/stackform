"""Cross-key rules of the ``deploy:`` section.

They run on the schema-valid spec, so every rule may rely on the shapes the
schema enforces. Rules that need the generated settings or the output
directory live with the deploy generator instead.
"""

import keyword
from collections import Counter
from collections.abc import Callable, Iterator
from itertools import chain, combinations
from pathlib import Path
from typing import Any

from yaml_api_generator.parsers.errors import ConfigError

GENERATED_MODULE = "app"
FRONTEND_SERVICE = "frontend"
DOCKER_ONLY_KEYS = (("docker", "registry"), ("frontend", "source"))

DeployRule = Callable[[dict[str, Any], Path], Iterator[ConfigError]]


def _error(code: str, message: str, path: str, hint: str | None = None) -> ConfigError:
    return ConfigError(code=code, message=message, path=f"deploy.{path}", hint=hint)


def _spec_subdirectory(relative: str, spec_dir: Path) -> Path | None:
    """The resolved directory when it lies strictly below the spec directory."""
    resolved_spec = spec_dir.resolve()
    source = (spec_dir / relative).resolve()
    return source if source != resolved_spec and source.is_relative_to(resolved_spec) else None


def _processes(deploy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return deploy.get("backend", {}).get("processes", {})


def _package_modules(deploy: dict[str, Any], spec_dir: Path) -> dict[int, str]:
    """Module name, by list index, of every package placed below the spec: its directory basename."""
    sources = (_spec_subdirectory(package, spec_dir) for package in deploy.get("backend", {}).get("packages", []))
    return {index: source.name for index, source in enumerate(sources) if source is not None}


def _docker_only(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    if deploy["runtime"] == "docker":
        return
    for section, key in DOCKER_ONLY_KEYS:
        if key in deploy.get(section, {}):
            yield _error(
                "DEPLOY_DOCKER_ONLY", f"'{section}.{key}' requires the docker runtime", f"{section}.{key}",
                "Set deploy.runtime to docker or remove the key",
            )


def _image_or_registry(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    if {"image", "registry"} <= deploy.get("docker", {}).keys():
        yield _error(
            "DEPLOY_IMAGE_REGISTRY_EXCLUSIVE", "docker.image and docker.registry are mutually exclusive",
            "docker", "docker.image is a base image; docker.registry is where built images are pushed",
        )


def _registry_required(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    docker = deploy.get("docker", {})
    builds_images = (
        "packages" in deploy.get("backend", {})
        or "processes" in deploy.get("backend", {})
        or "source" in deploy.get("frontend", {})
    )
    if (
        deploy["runtime"] == "docker"
        and deploy.get("environments")
        and builds_images
        and docker.get("delivery", "registry") == "registry"
        and "registry" not in docker
    ):
        yield _error(
            "DEPLOY_REGISTRY_REQUIRED", "environments that ship built images need docker.registry",
            "docker.registry", "Set docker.registry, or docker.delivery: ssh to copy images over SSH",
        )


def _package_location(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    for index, package in enumerate(deploy.get("backend", {}).get("packages", [])):
        source = _spec_subdirectory(package, spec_dir)
        if source is None:
            yield _error(
                "DEPLOY_PACKAGE_OUTSIDE_SPEC", f"package '{package}' must be a subdirectory of the spec directory",
                f"backend.packages[{index}]",
            )
        elif not source.is_dir():
            yield _error(
                "DEPLOY_PACKAGE_NOT_FOUND", f"package directory not found: {source}", f"backend.packages[{index}]",
            )


def _package_names(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    names = _package_modules(deploy, spec_dir)
    counts = Counter(names.values())
    for index, name in names.items():
        if not name.isidentifier() or keyword.iskeyword(name) or name == GENERATED_MODULE:
            yield _error(
                "DEPLOY_PACKAGE_NAME_INVALID", f"package '{name}' is not an importable module name",
                f"backend.packages[{index}]", f"Use a Python identifier other than '{GENERATED_MODULE}'",
            )
        elif counts[name] > 1:
            yield _error(
                "DEPLOY_PACKAGE_DUPLICATE", f"package name '{name}' is staged more than once",
                f"backend.packages[{index}]",
            )


def _single_asgi_process(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    processes = _processes(deploy)
    asgi = [name for name, process in processes.items() if "asgi" in process]
    if processes and len(asgi) != 1:
        yield _error(
            "DEPLOY_ASGI_PROCESS_COUNT", f"exactly one process must declare asgi, found {len(asgi)}",
            "backend.processes", "The asgi process serves HTTP; the others run a command",
        )


def _asgi_module_known(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    modules = {GENERATED_MODULE, *_package_modules(deploy, spec_dir).values()}
    asgi = {name: process["asgi"] for name, process in _processes(deploy).items() if "asgi" in process}
    for name, target in asgi.items():
        root = target.partition(":")[0].partition(".")[0]
        if root not in modules:
            yield _error(
                "DEPLOY_ASGI_MODULE_UNKNOWN", f"asgi module '{root}' is neither generated nor a staged package",
                f"backend.processes.{name}.asgi", "Add its directory to backend.packages",
            )


def _process_names_unique(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    taken = {FRONTEND_SERVICE, *deploy.get("services", {})}
    for name in sorted(_processes(deploy).keys() & taken):
        yield _error(
            "DEPLOY_PROCESS_NAME_CLASH", f"process '{name}' clashes with another deploy service",
            f"backend.processes.{name}",
        )


def _frontend_source(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    relative = deploy.get("frontend", {}).get("source")
    if relative is None:
        return
    source = _spec_subdirectory(relative, spec_dir)
    if source is None:
        yield _error(
            "DEPLOY_FRONTEND_OUTSIDE_SPEC", f"frontend source '{relative}' must be a subdirectory of the spec directory",
            "frontend.source",
        )
    elif not (source / "package.json").is_file():
        yield _error(
            "DEPLOY_FRONTEND_NOT_FOUND", f"frontend source has no package.json: {source}", "frontend.source",
        )


def _frontend_names_disjoint(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    frontend = deploy.get("frontend", {})
    for first, second in combinations(("env", "args", "secrets"), 2):
        for name in sorted(set(frontend.get(first, [])) & set(frontend.get(second, []))):
            yield _error(
                "DEPLOY_FRONTEND_NAME_OVERLAP", f"'{name}' is listed in both frontend.{first} and frontend.{second}",
                f"frontend.{second}",
            )


def _environment_literals(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    for env_name, environment in deploy.get("environments", {}).items():
        for key, value in environment.get("env", {}).items():
            if "${" in value:
                yield _error(
                    "DEPLOY_ENV_VALUE_INTERPOLATED", f"'{key}' must be a literal value",
                    f"environments.{env_name}.env.{key}", "List values that come from CI under secrets",
                )


def _environment_secrets_disjoint(deploy: dict[str, Any], spec_dir: Path) -> Iterator[ConfigError]:
    for env_name, environment in deploy.get("environments", {}).items():
        for key in sorted(environment.get("env", {}).keys() & set(environment.get("secrets", []))):
            yield _error(
                "DEPLOY_ENV_SECRET_OVERLAP", f"'{key}' is both a literal env value and a secret",
                f"environments.{env_name}.secrets",
            )


_RULES: tuple[DeployRule, ...] = (
    _docker_only,
    _image_or_registry,
    _registry_required,
    _package_location,
    _package_names,
    _single_asgi_process,
    _asgi_module_known,
    _process_names_unique,
    _frontend_source,
    _frontend_names_disjoint,
    _environment_literals,
    _environment_secrets_disjoint,
)


def validate_spec_deploy(spec: dict[str, Any], spec_dir: Path) -> list[ConfigError]:
    """Every cross-key violation of the ``deploy:`` section."""
    deploy = spec.get("deploy")
    if not isinstance(deploy, dict):
        return []
    return list(chain.from_iterable(rule(deploy, spec_dir) for rule in _RULES))


def _unknown_keys(node: Any, schema: dict[str, Any], defs: dict[str, Any], path: str) -> Iterator[str]:
    schema = defs[schema["$ref"].rsplit("/", 1)[1]] if "$ref" in schema else schema
    known = schema.get("properties")
    if not isinstance(node, dict) or known is None:
        return
    for key, value in node.items():
        if key in known:
            yield from _unknown_keys(value, known[key], defs, f"{path}.{key}")
        else:
            yield f"{path}.{key}"


def warn_unknown_deploy_keys(spec: dict[str, Any], schema: dict[str, Any]) -> list[ConfigError]:
    """Warn about deploy keys the spec version ignores, such as v0.3 keys in a v0.2 spec."""
    if "deploy" not in spec:
        return []
    deploy_schema = schema.get("properties", {}).get("deploy", {"properties": {}})
    return [
        ConfigError(
            code="DEPLOY_KEY_IGNORED",
            message=f"'{path}' is not supported by this spec version and is ignored",
            path=path,
            hint='Upgrade to version: "0.3"',
            severity="warning",
        )
        for path in _unknown_keys(spec["deploy"], deploy_schema, schema.get("$defs", {}), "deploy")
    ]
