from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.engine import make_url

from ...ir import (
    IRDeploy,
    IRDeployDocker,
    IRDeployEnvironment,
    IRDeployFrontend,
    IRDeployProcess,
    IRDocument,
    IRPostgres,
)
from ..backend.builders import build_context
from ..backend.builders.settings_builder import build_settings_fields
from .context import (
    DeployContext,
    DeployDatastore,
    DeployFrontend,
    DeployPackage,
    DeployTarget,
    DockerDeployContext,
    GENERATED_FRONTEND,
    IMPLICIT_ENVIRONMENT,
    NPM_MANIFESTS,
    SystemdDeployContext,
)
from .file_deployments import build_file_deployments


def build_deploy_context(
    ir: IRDocument,
    spec_dir: Path,
    target: DeployTarget = DeployTarget(),
) -> DeployContext:
    """``target`` is the host of a bundle without environments; environments ignore it."""
    if ir.deploy is None:
        raise ValueError("spec has no 'deploy:' section")

    deploy = ir.deploy
    name = deploy.name or "app"
    mongo_db = ir.mongo.database
    context = build_context(ir)
    secret_fields = [f for f in build_settings_fields(context) if f.secret]
    secret_env_names = tuple(f.env_name for f in secret_fields)
    file_deployments = build_file_deployments(context.file_stores)
    env_vars = {
        **{var: "" for var in dict.fromkeys([*deploy.env_vars, *(f.env_name for f in secret_fields)])},
        **{key: value for fd in file_deployments for key, value in fd.host_env.items()},
    }
    datastores = (*_build_datastores(ir), *(fd.datastore for fd in file_deployments if fd.datastore))

    common = dict(
        name=name,
        port=deploy.port,
        runtime=deploy.runtime,
        mongo_local=deploy.mongo_local,
        mongo_db=mongo_db,
        env_vars=env_vars,
        has_auth=bool(ir.identityCollections),
        target=None if deploy.environments else target,
        datastores=datastores,
        environments=_environments(deploy, (f.env_name for f in secret_fields if f.generator)),
        processes=_validated_processes(deploy, datastores),
        packages=tuple(_package((spec_dir / package).resolve()) for package in deploy.backend.packages),
        system_packages=deploy.backend.system_packages,
        frontend=_frontend(deploy.frontend, spec_dir, ir.has_ui, secret_env_names),
        secret_env_names=secret_env_names,
    )

    if deploy.runtime == "docker":
        docker = deploy.docker or IRDeployDocker()
        defaults = {
            **{key: value for source in (*datastores, *file_deployments) for key, value in source.app_env.items()},
            "PORT": str(deploy.port),
            "FRONTEND_URL": "http://localhost",
        }
        app_environment = tuple(f"{key}=${{{key}:-{value}}}" for key, value in defaults.items()) + tuple(
            f"{f.env_name}=${{{f.env_name}}}" for f in secret_fields if f.env_name not in defaults
        )
        _validate_memory_limits(docker, common)
        return DockerDeployContext(
            **common,
            image=docker.image,
            registry=docker.registry,
            delivery=_delivery(docker),
            retain=docker.retain,
            memory_limits=docker.memory_limits,
            mongo_cache_gb=docker.mongo_cache_gb,
            extra_services=deploy.extra_services,
            include=deploy.include,
            app_environment=app_environment,
            app_volumes=tuple(fd.volume for fd in file_deployments if fd.volume),
        )

    if deploy.runtime == "systemd":
        sd = deploy.systemd
        return SystemdDeployContext(
            **common,
            user=sd.user if sd else "ubuntu",
            restart=sd.restart if sd else "on-failure",
        )

    raise ValueError(f"unknown runtime: {deploy.runtime}")


def _validate_memory_limits(docker: IRDeployDocker, common: dict) -> None:
    names = {p.name for p in common["processes"]}
    names.update(ds.service for ds in common["datastores"] if ds.local)
    if common["frontend"] is not None:
        names.add("frontend")
    if unknown := sorted(docker.memory_limits.keys() - names):
        raise ValueError(f"docker.memory_limits names unknown generated services: {unknown}")
    if docker.mongo_cache_gb is not None and not any(
        ds.local and ds.type == "mongodb" for ds in common["datastores"]
    ):
        raise ValueError("docker.mongo_cache_gb requires a local MongoDB datastore")


def _environments(deploy: IRDeploy, generated_secrets: Iterable[str]) -> tuple[IRDeployEnvironment, ...]:
    """The spec's environments, or the implicit one. Generated secrets are made on the host, never by CI."""
    generated = set(generated_secrets)
    for environment in deploy.environments:
        if clash := sorted(generated.intersection(environment.secrets)):
            raise ValueError(
                f"deploy environment '{environment.name}' lists generated secrets {clash}: "
                "they are generated on the host, remove them from its secrets"
            )
    return deploy.environments or (IMPLICIT_ENVIRONMENT,)


def _delivery(docker: IRDeployDocker) -> str:
    """How release images reach the host: pulled from the registry, copied over SSH,
    or, without a registry to pull from, built on the host from the shipped bundle."""
    return "host" if docker.delivery == "registry" and docker.registry is None else docker.delivery


def _validated_processes(deploy: IRDeploy, datastores: Iterable[DeployDatastore]) -> tuple[IRDeployProcess, ...]:
    """The backend processes, once none is named after a datastore service, which only the generator knows."""
    processes = deploy.backend.processes
    if clash := sorted({process.name for process in processes} & {ds.service for ds in datastores}):
        raise ValueError(f"deploy processes {clash} clash with datastore services of the same name")
    names = {p.name for p in processes} | {ds.service for ds in datastores if ds.local}
    names.update(name for name, _ in deploy.extra_services)
    for process in processes:
        if process.name in process.depends_on or process.depends_on.keys() - names:
            raise ValueError(f"process '{process.name}' depends on itself or an unknown service")
    return processes


def _package(source: Path) -> DeployPackage:
    requirements = sorted(path.relative_to(source).as_posix() for path in source.rglob("requirements.txt"))
    return DeployPackage(source=source, requirements=tuple(requirements))


def _frontend(
    frontend: IRDeployFrontend, spec_dir: Path, has_ui: bool, secrets: Iterable[str]
) -> DeployFrontend | None:
    """The frontend to deploy, once none of its public ``/config.js`` values is a backend secret."""
    if frontend.source is None:
        return GENERATED_FRONTEND if has_ui else None
    if clash := sorted(set(frontend.env).intersection(secrets)):
        raise ValueError(f"deploy frontend env {clash} would serve backend secrets to browsers in /config.js")
    root = (spec_dir / frontend.source).resolve()
    return DeployFrontend(
        **asdict(frontend), root=root, manifests=tuple(name for name in NPM_MANIFESTS if (root / name).is_file())
    )


def _build_datastores(ir: IRDocument) -> tuple[DeployDatastore, ...]:
    base_names = {"postgres": "postgres", "mongodb": "mongodb", "mongo": "mongodb"}
    type_counts = Counter(base_names.get(ds.type, ds.type) for ds in ir.datastores.values())
    seen: Counter = Counter()
    result: list[DeployDatastore] = []

    for name, ds in ir.datastores.items():
        base = base_names.get(ds.type, ds.type)
        seen[base] += 1
        service = base if type_counts[base] == 1 else f"{base}-{name}"
        result.append(
            _postgres_datastore(service, ds) if isinstance(ds, IRPostgres)
            else _mongo_datastore(service, ds)
        )
    return tuple(result)


def _postgres_datastore(service: str, ds: IRPostgres) -> DeployDatastore:
    url = make_url(ds.dsn)
    db = url.database or "app"
    user = url.username or "postgres"
    password = url.password or "postgres"
    local = url.host in (None, "localhost", "127.0.0.1")
    return DeployDatastore(
        service=service,
        type="postgres",
        image="postgres:16",
        local=local,
        app_env={"DATABASE_URL": f"postgresql+asyncpg://{user}:{password}@{service}:5432/{db}"},
        service_env={"POSTGRES_DB": db, "POSTGRES_USER": user, "POSTGRES_PASSWORD": password},
        volume=f"{service}_data",
        volume_path="/var/lib/postgresql/data",
    )


def _mongo_datastore(service: str, ds) -> DeployDatastore:
    local = "localhost" in ds.uri or "127.0.0.1" in ds.uri
    return DeployDatastore(
        service=service,
        type="mongodb",
        image="mongo:8",
        local=local,
        app_env={"MONGO_URI": f"mongodb://{service}:27017", "MONGO_DB": ds.database},
        service_env={},
        volume=f"{service}_data",
        volume_path="/data/db",
    )
