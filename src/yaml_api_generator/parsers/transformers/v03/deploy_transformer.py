"""v0.3 deploy keys: backend processes and packages, hand-written frontend, environments, registry."""

from dataclasses import replace
from typing import Any

from yaml_api_generator.ir import (
    IRDeploy,
    IRDeployBackend,
    IRDeployDocker,
    IRDeployEnvironment,
    IRDeployFrontend,
    IRDeployProcess,
)

from ..v02.deploy_transformer import DeployTransformer


def _process(name: str, data: dict[str, Any]) -> IRDeployProcess:
    command = data.get("command")
    return IRDeployProcess(
        name=name,
        asgi=data.get("asgi"),
        command=tuple(command) if isinstance(command, list) else command,
        env=dict(data.get("env", {})),
    )


def _backend(data: dict[str, Any]) -> IRDeployBackend:
    return IRDeployBackend(
        packages=tuple(data.get("packages", ())),
        system_packages=tuple(data.get("system_packages", ())),
        processes=(
            tuple(_process(name, process) for name, process in data.get("processes", {}).items())
            or IRDeployBackend().processes
        ),
    )


def _frontend(data: dict[str, Any]) -> IRDeployFrontend:
    defaults = IRDeployFrontend()
    return IRDeployFrontend(
        source=data.get("source"),
        build=data.get("build", defaults.build),
        output=data.get("output", defaults.output),
        env=tuple(data.get("env", ())),
        args=tuple(data.get("args", ())),
        secrets=tuple(data.get("secrets", ())),
    )


class V03DeployTransformer(DeployTransformer):
    """Extends the v0.2 deploy IR with the v0.3 keys."""

    def build(self, deploy_data: Any, mongo_config: dict[str, Any]) -> IRDeploy | None:
        deploy = super().build(deploy_data, mongo_config)
        if deploy is None:
            return None
        return replace(
            deploy,
            backend=_backend(deploy_data.get("backend", {})),
            frontend=_frontend(deploy_data.get("frontend", {})),
            environments=tuple(
                IRDeployEnvironment(name=name, env=dict(env.get("env", {})), secrets=tuple(env.get("secrets", ())))
                for name, env in deploy_data.get("environments", {}).items()
            ),
        )

    def _docker(self, docker_data: dict[str, Any]) -> IRDeployDocker:
        defaults = IRDeployDocker()
        return IRDeployDocker(
            image=docker_data.get("image"),
            registry=docker_data.get("registry"),
            delivery=docker_data.get("delivery", defaults.delivery),
            retain=docker_data.get("retain", defaults.retain),
        )
