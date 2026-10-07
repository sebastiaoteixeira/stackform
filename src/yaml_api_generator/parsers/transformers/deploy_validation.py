"""Cross-key rules of the ``deploy:`` section.

They run on the schema-valid spec, so every rule may rely on the shapes the
schema enforces. Rules that need the generated settings or the output
directory live with the deploy generator instead.
"""

import keyword
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cached_property
from itertools import chain, combinations
from pathlib import Path
from typing import Any

from yaml_api_generator.ir.api import FRONTEND_SERVICE, GENERATED_ASGI_PROCESS
from yaml_api_generator.parsers.errors import ConfigError

GENERATED_MODULE = GENERATED_ASGI_PROCESS.asgi.partition(":")[0]
DOCKER_ONLY_KEYS = (("docker", "registry"), ("docker", "memory_limits"), ("docker", "mongo_cache_gb"), ("frontend", "source"))
DEPLOY_VERSIONS = ("0.3",)
TEMPLATE_MARKERS = ("${", "{{", "{%", "{#")


def _error(code: str, message: str, path: str, hint: str | None = None) -> ConfigError:
    return ConfigError(code=code, message=message, path=f"deploy.{path}", hint=hint)


@dataclass(frozen=True)
class DeploySpec:
    """The schema-valid spec whose ``deploy:`` section the rules check, and the directory it lives in."""

    spec: dict[str, Any]
    spec_dir: Path

    @property
    def deploy(self) -> dict[str, Any]:
        return self.spec["deploy"]

    @property
    def ui(self) -> dict[str, Any]:
        return self.spec.get("ui") or {}

    @property
    def processes(self) -> dict[str, dict[str, Any]]:
        return self.deploy.get("backend", {}).get("processes", {})

    @property
    def environments(self) -> dict[str, dict[str, Any]]:
        return self.deploy.get("environments", {})

    def subdirectory(self, relative: str) -> Path | None:
        """The resolved directory when it lies strictly below the spec directory."""
        resolved_spec = self.spec_dir.resolve()
        source = (self.spec_dir / relative).resolve()
        return source if source != resolved_spec and source.is_relative_to(resolved_spec) else None

    @cached_property
    def package_modules(self) -> dict[int, str]:
        """Module name, by list index, of every package placed below the spec: its directory basename."""
        sources = (self.subdirectory(package) for package in self.deploy.get("backend", {}).get("packages", []))
        return {index: source.name for index, source in enumerate(sources) if source is not None}


DeployRule = Callable[[DeploySpec], Iterator[ConfigError]]


def _docker_only(spec: DeploySpec) -> Iterator[ConfigError]:
    if spec.deploy["runtime"] == "docker":
        return
    for section, key in DOCKER_ONLY_KEYS:
        if key in spec.deploy.get(section, {}):
            yield _error(
                "DEPLOY_DOCKER_ONLY", f"'{section}.{key}' requires the docker runtime", f"{section}.{key}",
                "Set deploy.runtime to docker or remove the key",
            )


def _image_or_registry(spec: DeploySpec) -> Iterator[ConfigError]:
    if {"image", "registry"} <= spec.deploy.get("docker", {}).keys():
        yield _error(
            "DEPLOY_IMAGE_REGISTRY_EXCLUSIVE", "docker.image and docker.registry are mutually exclusive",
            "docker", "docker.image is a prebuilt backend image pulled as-is; docker.registry is where built images are pushed",
        )


def _registry_required(spec: DeploySpec) -> Iterator[ConfigError]:
    deploy = spec.deploy
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


def _package_location(spec: DeploySpec) -> Iterator[ConfigError]:
    for index, package in enumerate(spec.deploy.get("backend", {}).get("packages", [])):
        source = spec.subdirectory(package)
        if source is None:
            yield _error(
                "DEPLOY_PACKAGE_OUTSIDE_SPEC", f"package '{package}' must be a subdirectory of the spec directory",
                f"backend.packages[{index}]",
            )
        elif not source.is_dir():
            yield _error(
                "DEPLOY_PACKAGE_NOT_FOUND", f"package directory not found: {source}", f"backend.packages[{index}]",
            )


def _package_names(spec: DeploySpec) -> Iterator[ConfigError]:
    names = spec.package_modules
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


def _single_asgi_process(spec: DeploySpec) -> Iterator[ConfigError]:
    asgi = [name for name, process in spec.processes.items() if "asgi" in process]
    if spec.processes and len(asgi) != 1:
        yield _error(
            "DEPLOY_ASGI_PROCESS_COUNT", f"exactly one process must declare asgi, found {len(asgi)}",
            "backend.processes", "The asgi process serves HTTP; the others run a command",
        )


def _asgi_module_known(spec: DeploySpec) -> Iterator[ConfigError]:
    modules = {GENERATED_MODULE, *spec.package_modules.values()}
    asgi = {name: process["asgi"] for name, process in spec.processes.items() if "asgi" in process}
    for name, target in asgi.items():
        root = target.partition(":")[0].partition(".")[0]
        if root not in modules:
            yield _error(
                "DEPLOY_ASGI_MODULE_UNKNOWN", f"asgi module '{root}' is neither generated nor a staged package",
                f"backend.processes.{name}.asgi", "Add its directory to backend.packages",
            )


def _process_names_unique(spec: DeploySpec) -> Iterator[ConfigError]:
    taken = {FRONTEND_SERVICE, *spec.deploy.get("services", {})}
    for name in sorted(spec.processes.keys() & taken):
        yield _error(
            "DEPLOY_PROCESS_NAME_CLASH", f"process '{name}' clashes with another deploy service",
            f"backend.processes.{name}",
        )


def _frontend_source(spec: DeploySpec) -> Iterator[ConfigError]:
    relative = spec.deploy.get("frontend", {}).get("source")
    if relative is None:
        return
    source = spec.subdirectory(relative)
    if source is None:
        yield _error(
            "DEPLOY_FRONTEND_OUTSIDE_SPEC", f"frontend source '{relative}' must be a subdirectory of the spec directory",
            "frontend.source",
        )
    elif not (source / "package.json").is_file():
        yield _error(
            "DEPLOY_FRONTEND_NOT_FOUND", f"frontend source has no package.json: {source}", "frontend.source",
        )


def _frontend_names_disjoint(spec: DeploySpec) -> Iterator[ConfigError]:
    frontend = spec.deploy.get("frontend", {})
    for first, second in combinations(("env", "args", "secrets"), 2):
        for name in sorted(set(frontend.get(first, [])) & set(frontend.get(second, []))):
            yield _error(
                "DEPLOY_FRONTEND_NAME_OVERLAP", f"'{name}' is listed in both frontend.{first} and frontend.{second}",
                f"frontend.{second}",
            )


def _environment_literals(spec: DeploySpec) -> Iterator[ConfigError]:
    for env_name, environment in spec.environments.items():
        for key, value in environment.get("env", {}).items():
            if any(marker in value for marker in TEMPLATE_MARKERS):
                yield _error(
                    "DEPLOY_ENV_VALUE_INTERPOLATED", f"'{key}' must be a literal value, not a template",
                    f"environments.{env_name}.env.{key}", "List values that come from CI under secrets",
                )


def _environment_secrets_disjoint(spec: DeploySpec) -> Iterator[ConfigError]:
    for env_name, environment in spec.environments.items():
        for key in sorted(environment.get("env", {}).keys() & set(environment.get("secrets", []))):
            yield _error(
                "DEPLOY_ENV_SECRET_OVERLAP", f"'{key}' is both a literal env value and a secret",
                f"environments.{env_name}.secrets",
            )


def _frontend_source_without_ui(spec: DeploySpec) -> Iterator[ConfigError]:
    if "source" in spec.deploy.get("frontend", {}) and spec.ui.get("frontend"):
        yield _error(
            "DEPLOY_FRONTEND_SOURCE_WITH_UI", "frontend.source and ui.frontend both define the frontend",
            "frontend.source", "Keep the hand-written frontend or the generated one, not both",
        )


def _frontend_env_public(spec: DeploySpec) -> Iterator[ConfigError]:
    public = set(spec.deploy.get("frontend", {}).get("env", []))
    for env_name, environment in spec.environments.items():
        for key in sorted(public & set(environment.get("secrets", []))):
            yield _error(
                "DEPLOY_FRONTEND_ENV_SECRET", f"'{key}' is served to browsers in /config.js but listed as a secret",
                f"environments.{env_name}.secrets", "Values in /config.js are public: keep secrets out of frontend.env",
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
    _frontend_source_without_ui,
    _frontend_env_public,
    _environment_literals,
    _environment_secrets_disjoint,
)


def validate_spec_deploy(spec: dict[str, Any], spec_dir: Path) -> list[ConfigError]:
    """Every cross-key violation of the ``deploy:`` section."""
    if not isinstance(spec.get("deploy"), dict):
        return []
    deploy_spec = DeploySpec(spec, spec_dir)
    return list(chain.from_iterable(rule(deploy_spec) for rule in _RULES))


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


def check_spec_deploy(spec: dict[str, Any], spec_dir: Path, schema: dict[str, Any]) -> list[ConfigError]:
    """Cross-key violations where the spec version supports ``deploy:``; warnings about the keys it ignores elsewhere."""
    if str(spec.get("version", "")) in DEPLOY_VERSIONS:
        return validate_spec_deploy(spec, spec_dir)
    return warn_unknown_deploy_keys(spec, schema)
