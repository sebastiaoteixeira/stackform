import shlex
from dataclasses import dataclass, field
from pathlib import Path

from ...ir import IRDeployEnvironment, IRDeployFrontend, IRDeployProcess
from ...ir.api import FRONTEND_SERVICE, GENERATED_ASGI_PROCESS


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


NPM_MANIFESTS = ("package.json", "package-lock.json", ".npmrc")


@dataclass(frozen=True)
class DeployFrontend(IRDeployFrontend):
    """The frontend image. A hand-written ``source`` is staged from ``root`` and installed
    from its ``manifests``, the ``NPM_MANIFESTS`` it has; a lockfile selects ``npm ci``."""

    root: Path | None = None
    manifests: tuple[str, ...] = NPM_MANIFESTS[:1]

    @property
    def locked(self) -> bool:
        return "package-lock.json" in self.manifests


GENERATED_FRONTEND = DeployFrontend(env=("VITE_API_BASE_URL",))

IMPLICIT_ENVIRONMENT = IRDeployEnvironment(name="default")


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
    environments: tuple[IRDeployEnvironment, ...] = (IMPLICIT_ENVIRONMENT,)
    processes: tuple[IRDeployProcess, ...] = (GENERATED_ASGI_PROCESS,)
    packages: tuple[DeployPackage, ...] = ()
    system_packages: tuple[str, ...] = ()
    frontend: DeployFrontend | None = None
    secret_env_names: tuple[str, ...] = ()

    @property
    def asgi_process(self) -> IRDeployProcess:
        return next(process for process in self.processes if process.asgi)

    def project(self, environment: IRDeployEnvironment) -> str:
        """The compose project and inventory host of ``environment``. A bundle without
        environments keeps the project, and so the volumes, it has always had."""
        return self.name if self.target else f"{self.name}-{environment.name}"

    @property
    def host_env(self) -> dict[str, str]:
        """Remote environment values that neither the environments nor the host's generated secrets set."""
        return {name: value for name, value in self.env_vars.items() if name not in self.secret_env_names}


@dataclass(frozen=True)
class DockerDeployContext(DeployContext):
    image: str | None = None
    registry: str | None = None
    delivery: str = "host"
    retain: int = 3
    memory_limits: dict[str, str] = field(default_factory=dict)
    mongo_cache_gb: float | None = None
    extra_services: tuple[tuple[str, dict], ...] = field(default_factory=tuple)
    include: tuple[str, ...] = field(default_factory=tuple)
    app_environment: tuple[str, ...] = field(default_factory=tuple)
    app_volumes: tuple[DeployVolume, ...] = field(default_factory=tuple)

    @property
    def backend_image(self) -> str:
        return self.image or self._release_image("backend")

    @property
    def frontend_image(self) -> str:
        return self._release_image(FRONTEND_SERVICE)

    @property
    def builds_on_host(self) -> bool:
        """Without a registry or an SSH copy, the host builds every image not pulled as-is."""
        return self.delivery == "host" and (self.image is None or self.frontend is not None)

    @property
    def release_repositories(self) -> tuple[str, ...]:
        """Repositories of the images each release tags, pruned on the host beyond ``retain``."""
        components = (*(() if self.image else ("backend",)), *((FRONTEND_SERVICE,) if self.frontend else ()))
        return tuple(self._repository(component) for component in components)

    @property
    def registry_host(self) -> str | None:
        """The registry to log in to; a first path component without a dot, colon or
        ``localhost`` is a Docker Hub namespace, as Docker reads image references."""
        if self.registry is None:
            return None
        host = self.registry.partition("/")[0]
        return host if "." in host or ":" in host or host == "localhost" else "docker.io"

    def _repository(self, component: str) -> str:
        """Without a registry, images are named after the app and never leave the host they reach."""
        return f"{self.registry or self.name}/{component}"

    def _release_image(self, component: str) -> str:
        return f"{self._repository(component)}:${{IMAGE_TAG:-latest}}"


@dataclass(frozen=True)
class SystemdDeployContext(DeployContext):
    user: str = "ubuntu"
    restart: str = "on-failure"

    @property
    def host_env(self) -> dict[str, str]:
        """Unlike compose's ``${VAR:-default}``, an empty value in a unit's environment file
        masks the app's own default, so only values the bundle knows are rendered."""
        return {name: value for name, value in super().host_env.items() if value}

    @property
    def requirements(self) -> tuple[str, ...]:
        """Requirement files installed into the project's virtualenv, relative to the project directory."""
        return ("requirements.txt", *(f"{p.bundle_path}/{r}" for p in self.packages for r in p.requirements))

    @staticmethod
    def unit_suffix(process: IRDeployProcess) -> str:
        """Units are named ``<project><suffix>.service``; the generated app keeps the unit it has always had."""
        return "" if process == GENERATED_ASGI_PROCESS else f"-{process.name}"

    def command(self, process: IRDeployProcess) -> str:
        if process.asgi:
            return shlex.join(("uvicorn", process.asgi, "--host", "0.0.0.0", "--port", str(self.port)))
        return process.command if isinstance(process.command, str) else shlex.join(process.command)
