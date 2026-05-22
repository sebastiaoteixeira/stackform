from dataclasses import dataclass, field


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
    extra_services: tuple[tuple[str, dict], ...] = field(default_factory=tuple)
    include: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SystemdDeployContext(DeployContext):
    user: str = "ubuntu"
    restart: str = "on-failure"