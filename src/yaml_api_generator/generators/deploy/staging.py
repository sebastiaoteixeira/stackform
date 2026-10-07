"""Copies hand-written directories next to the spec into the deploy bundle, so it is self-contained."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from .context import DeployFrontendSource, DeployPackage

FRONTEND_DIR = "frontend"


@dataclass(frozen=True)
class BundleStager:
    spec_dir: Path
    output_dir: Path

    def stage(self, source: Path, destination: str, owner: str) -> str:
        """Copy ``source`` to ``destination`` in the bundle and return its bundle-relative path."""
        source = source.resolve()
        if not source.is_dir():
            raise ValueError(f"{owner} not found: {source}")
        if any(path.resolve().is_relative_to(source) for path in (self.spec_dir, self.output_dir)):
            raise ValueError(f"{owner} must be a subdirectory of the spec that excludes the output: {source}")
        shutil.copytree(source, self.output_dir / destination, dirs_exist_ok=True)
        return f"./{destination}"

    def services(self, services: tuple[tuple[str, dict], ...]) -> tuple[tuple[str, dict], ...]:
        """Stage each service's build context and point its ``build:`` (string or ``build.context``) at the copy."""
        return tuple((name, self._service(name, config)) for name, config in services)

    def packages(self, packages: tuple[DeployPackage, ...]) -> None:
        for package in packages:
            self.stage(package.source, package.bundle_path, f"deploy package '{package.name}'")

    def frontend(self, frontend: DeployFrontendSource | None) -> None:
        if frontend is not None:
            self.stage(frontend.source, FRONTEND_DIR, "deploy frontend source")

    def _service(self, name: str, config: dict) -> dict:
        build = config.get("build")
        context = build.get("context") if isinstance(build, dict) else build
        if not isinstance(context, str) or not context:
            return config
        source = (self.spec_dir / context).resolve()
        local = self.stage(source, source.name, f"deploy service '{name}' build context")
        return {**config, "build": {**build, "context": local} if isinstance(build, dict) else local}
