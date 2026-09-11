from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeployDatastore:
    service: str
    type: str
    image: str
    local: bool
    app_env: dict[str, str]
    service_env: dict[str, str]
    volume: str | None
    volume_path: str | None


@dataclass(frozen=True)
class DeployContext:
    name: str
    port: int
    runtime: str
    mongo_local: bool
    mongo_db: str
    env_vars: dict[str, str]
    has_auth: bool
    has_frontend: bool
    host: str
    ssh_user: str
    ssh_key: str
    datastores: tuple[DeployDatastore, ...] = ()


@dataclass(frozen=True)
class DockerDeployContext(DeployContext):
    image: str | None = None
    extra_services: tuple[tuple[str, dict], ...] = field(default_factory=tuple)
    include: tuple[str, ...] = field(default_factory=tuple)
    app_environment: tuple[str, ...] = field(default_factory=tuple)
    secret_env_names: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SystemdDeployContext(DeployContext):
    user: str = "ubuntu"
    restart: str = "on-failure"