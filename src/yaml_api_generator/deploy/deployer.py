from pathlib import Path
from typing import Type

from ..parsing.parser import load_and_generate_ir
from .base import DeployGenerator
from .deploy_context_builder import build_deploy_context
from .generators.docker.generator import DockerDeployGenerator
from .generators.systemd.generator import SystemdDeployGenerator

_BACKENDS: dict[str, Type[DeployGenerator]] = {
    "docker": DockerDeployGenerator,
    "systemd": SystemdDeployGenerator,
}


def deploy_api(
    yaml_file: str,
    schema_file: str | None,
    host: str,
    ssh_user: str,
    ssh_key: str,
    output_dir: str,
) -> None:
    raw_text = Path(yaml_file).read_text()
    ir = load_and_generate_ir(yaml_file, schema_file)
    ctx = build_deploy_context(ir, yaml_file, raw_text, host, ssh_user, ssh_key)
    backend_cls = _BACKENDS.get(ctx.runtime)
    if backend_cls is None:
        raise ValueError(f"no backend for runtime: {ctx.runtime}")
    backend_cls().generate(ctx, Path(output_dir))
