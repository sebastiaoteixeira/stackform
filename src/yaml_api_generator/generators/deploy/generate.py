from pathlib import Path
from typing import Type

from ...ir import IRDocument
from .base import DeployGenerator
from .context import DeployTarget
from .context_builder import build_deploy_context
from .docker.generator import DockerDeployGenerator
from .systemd.generator import SystemdDeployGenerator

_BACKENDS: dict[str, Type[DeployGenerator]] = {
    "docker": DockerDeployGenerator,
    "systemd": SystemdDeployGenerator,
}


def generate_deploy(
    ir: IRDocument,
    output_dir: str,
    spec_dir: str | Path,
    target: DeployTarget = DeployTarget(),
) -> None:
    ctx = build_deploy_context(ir, Path(spec_dir), target)
    backend_cls = _BACKENDS.get(ctx.runtime)
    if backend_cls is None:
        raise ValueError(f"no backend for runtime: {ctx.runtime}")
    backend_cls().generate(ctx, Path(output_dir), Path(spec_dir))
