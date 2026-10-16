"""Deploy configuration transformation to IR."""

import re
from collections.abc import Iterator
from typing import Any

from yaml_api_generator.ir import IRDeploy, IRDeployDocker, IRDeploySystemd

_ENV_TOKEN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-[^}]*)?\}")


def _strings(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)


class DeployTransformer:
    """Builds the deploy IR from the v0.2 ``deploy:`` keys."""

    def build(self, deploy_data: Any, mongo_config: dict[str, Any]) -> IRDeploy | None:
        """Deploy IR, or None when the spec configures no deploy runtime."""
        if not isinstance(deploy_data, dict) or not deploy_data.get("runtime"):
            return None

        systemd_data = deploy_data.get("systemd")
        mongo_uri = mongo_config.get("uri", "mongodb://localhost:27017")
        return IRDeploy(
            runtime=str(deploy_data["runtime"]),
            name=deploy_data.get("name"),
            port=int(deploy_data.get("port", 8000)),
            mongo_local=not mongo_config or "localhost" in mongo_uri or "127.0.0.1" in mongo_uri,
            env_vars=tuple(sorted({
                name for text in _strings(deploy_data) for name in _ENV_TOKEN.findall(text)
            })),
            docker=self._docker(deploy_data["docker"]) if isinstance(deploy_data.get("docker"), dict) else None,
            systemd=(
                IRDeploySystemd(
                    user=systemd_data.get("user", "ubuntu"),
                    restart=systemd_data.get("restart", "on-failure"),
                )
                if isinstance(systemd_data, dict)
                else None
            ),
            extra_services=tuple(deploy_data.get("services", {}).items()),
            include=tuple(deploy_data.get("include", [])),
        )

    def _docker(self, docker_data: dict[str, Any]) -> IRDeployDocker:
        return IRDeployDocker(image=docker_data.get("image"))
