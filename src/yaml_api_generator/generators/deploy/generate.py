from pathlib import Path
from typing import Type

from ...ir import IRDocument
from .base import DeployGenerator
from .context_builder import build_deploy_context
from .docker.generator import DockerDeployGenerator
from .systemd.generator import SystemdDeployGenerator

_BACKENDS: dict[str, Type[DeployGenerator]] = {
    "docker": DockerDeployGenerator,
    "systemd": SystemdDeployGenerator,
}


def generate_deploy(
    ir: IRDocument,
    host: str,
    ssh_user: str,
    ssh_key: str,
    output_dir: str,
) -> None:
    ctx = build_deploy_context(ir, host, ssh_user, ssh_key)
    backend_cls = _BACKENDS.get(ctx.runtime)
    if backend_cls is None:
        raise ValueError(f"no backend for runtime: {ctx.runtime}")
    backend_cls().generate(ctx, Path(output_dir))