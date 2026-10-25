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
    command: str | None = None


@dataclass(frozen=True)
class DeployVolume:
    name: str
    path: str


@dataclass(frozen=True)
class DeployContext:
    name: str
    port: int
    runtime: str
    application: str
    env_vars: dict[str, str]
    has_auth: bool
    has_frontend: bool
    host: str
    ssh_user: str
    ssh_key: str
    datastores: tuple[DeployDatastore, ...] = ()

    @property
    def local_datastores(self) -> tuple[DeployDatastore, ...]:
        return tuple(ds for ds in self.datastores if ds.local)

    @property
    def local_mongo(self) -> bool:
        return any(ds.type == "mongodb" for ds in self.local_datastores)


@dataclass(frozen=True)
class DockerDeployContext(DeployContext):
    image: str | None = None
    extra_services: tuple[tuple[str, dict], ...] = field(default_factory=tuple)
    include: tuple[str, ...] = field(default_factory=tuple)
    app_environment: tuple[str, ...] = field(default_factory=tuple)
    secret_env_names: tuple[str, ...] = field(default_factory=tuple)
    app_volumes: tuple[DeployVolume, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SystemdDeployContext(DeployContext):
    user: str = "ubuntu"
    restart: str = "on-failure"