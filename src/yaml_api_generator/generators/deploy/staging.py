"""Copies hand-written directories next to the spec into the deploy bundle, so it is self-contained."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from ...ir.api import FRONTEND_SERVICE
from .context import DeployFrontend, DeployPackage

# Local state that is either secret or built for the developer's machine; the images build their own.
_LOCAL_STATE = shutil.ignore_patterns(".git", ".env", ".env.*", ".venv", "node_modules", "__pycache__")


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
            raise ValueError(f"{owner} must not contain the spec or the output directory: {source}")
        shutil.copytree(source, self.output_dir / destination, dirs_exist_ok=True, ignore=_LOCAL_STATE)
        return f"./{destination}"

    def services(self, services: tuple[tuple[str, dict], ...]) -> tuple[tuple[str, dict], ...]:
        """Stage each service's build context and point its ``build:`` (string or ``build.context``) at the copy."""
        return tuple((name, self._service(name, config)) for name, config in services)

    def packages(self, packages: tuple[DeployPackage, ...]) -> None:
        for package in packages:
            self.stage(package.source, package.bundle_path, f"deploy package '{package.name}'")

    def frontend(self, frontend: DeployFrontend | None) -> None:
        if frontend is not None and frontend.root is not None:
            self.stage(frontend.root, FRONTEND_SERVICE, "deploy frontend source")

    def _service(self, name: str, config: dict) -> dict:
        build = config.get("build")
        context = build.get("context") if isinstance(build, dict) else build
        if not isinstance(context, str) or not context:
            return config
        source = (self.spec_dir / context).resolve()
        local = self.stage(source, source.name, f"deploy service '{name}' build context")
        return {**config, "build": {**build, "context": local} if isinstance(build, dict) else local}
