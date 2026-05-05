from dataclasses import dataclass


@dataclass(frozen=True)
class DeployContext:
    name: str
    port: int
    runtime: str
    mongo_local: bool
    mongo_db: str
    env_vars: list[str]
    has_auth: bool
    has_frontend: bool
    host: str
    ssh_user: str
    ssh_key: str


@dataclass(frozen=True)
class DockerDeployContext(DeployContext):
    image: str | None = None


@dataclass(frozen=True)
class SystemdDeployContext(DeployContext):
    user: str = "ubuntu"
    restart: str = "on-failure"