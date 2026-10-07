from dataclasses import dataclass, field
from pathlib import Path

from ...ir import IRDeployEnvironment, IRDeployProcess
from ...ir.api import GENERATED_ASGI_PROCESS


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
class DeployTarget:
    """The SSH host of a bundle without environments; environments name theirs at deploy time."""

    host: str = "localhost"
    user: str = "ubuntu"
    ssh_key: str = "~/.ssh/id_rsa"


@dataclass(frozen=True)
class DeployPackage:
    """A hand-written package staged as ``packages/<name>`` and imported as module ``name``."""

    source: Path
    requirements: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.source.name

    @property
    def bundle_path(self) -> str:
        return f"packages/{self.name}"


@dataclass(frozen=True)
class DeployFrontend:
    """The frontend image. ``source`` is a hand-written app built in place of the generated one;
    ``env`` names are served at runtime through ``/config.js``; ``locked`` selects ``npm ci``."""

    source: Path | None = None
    build: str = "npm run build"
    output: str = "dist"
    env: tuple[str, ...] = ()
    args: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    locked: bool = False


GENERATED_FRONTEND = DeployFrontend(env=("VITE_API_BASE_URL",))


@dataclass(frozen=True)
class DeployContext:
    name: str
    port: int
    runtime: str
    mongo_local: bool
    mongo_db: str
    env_vars: dict[str, str]
    has_auth: bool
    target: DeployTarget | None
    datastores: tuple[DeployDatastore, ...] = ()
    environments: tuple[IRDeployEnvironment, ...] = ()
    processes: tuple[IRDeployProcess, ...] = (GENERATED_ASGI_PROCESS,)
    packages: tuple[DeployPackage, ...] = ()
    system_packages: tuple[str, ...] = ()
    frontend: DeployFrontend | None = None

    @property
    def has_frontend(self) -> bool:
        return self.frontend is not None

    @property
    def asgi_process(self) -> IRDeployProcess:
        return next(process for process in self.processes if process.asgi)


@dataclass(frozen=True)
class DockerDeployContext(DeployContext):
    image: str | None = None
    registry: str | None = None
    delivery: str = "registry"
    retain: int = 3
    extra_services: tuple[tuple[str, dict], ...] = field(default_factory=tuple)
    include: tuple[str, ...] = field(default_factory=tuple)
    app_environment: tuple[str, ...] = field(default_factory=tuple)
    secret_env_names: tuple[str, ...] = field(default_factory=tuple)
    app_volumes: tuple[DeployVolume, ...] = field(default_factory=tuple)

    @property
    def backend_image(self) -> str:
        return self.image or self._release_image("backend")

    @property
    def frontend_image(self) -> str:
        return self._release_image("frontend")

    def _release_image(self, component: str) -> str:
        """Without a registry, images are named after the app and only ever built on the host."""
        return f"{self.registry or self.name}/{component}:${{IMAGE_TAG:-latest}}"


@dataclass(frozen=True)
class SystemdDeployContext(DeployContext):
    user: str = "ubuntu"
    restart: str = "on-failure"
