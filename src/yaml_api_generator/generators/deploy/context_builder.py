from collections import Counter
from collections.abc import Iterable
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
    DeployFrontendSource,
    DeployPackage,
    DeployTarget,
    DockerDeployContext,
    SystemdDeployContext,
)
from .file_deployments import build_file_deployments

# Named after the inventory host that bundles without environments have always deployed to.
IMPLICIT_ENVIRONMENT = IRDeployEnvironment(name="app")


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
        has_frontend=ir.has_ui or deploy.frontend.source is not None,
        target=None if deploy.environments else target,
        datastores=datastores,
        environments=_environments(deploy, (f.env_name for f in secret_fields if f.generator)),
        processes=_processes(deploy, datastores),
        packages=tuple(_package((spec_dir / package).resolve()) for package in deploy.backend.packages),
        system_packages=deploy.backend.system_packages,
        frontend_source=_frontend_source(deploy.frontend, spec_dir),
    )

    if deploy.runtime == "docker":
        docker = deploy.docker or IRDeployDocker()
        secret_env_names = tuple(f.env_name for f in secret_fields)
        defaults = {
            **{key: value for source in (*datastores, *file_deployments) for key, value in source.app_env.items()},
            "PORT": str(deploy.port),
            "FRONTEND_URL": "http://localhost",
        }
        app_environment = tuple(f"{key}=${{{key}:-{value}}}" for key, value in defaults.items()) + tuple(
            f"{f.env_name}=${{{f.env_name}}}" for f in secret_fields if f.env_name not in defaults
        )
        return DockerDeployContext(
            **common,
            image=docker.image,
            registry=docker.registry,
            delivery=docker.delivery,
            retain=docker.retain,
            extra_services=deploy.extra_services,
            include=deploy.include,
            app_environment=app_environment,
            secret_env_names=secret_env_names,
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


def _processes(deploy: IRDeploy, datastores: Iterable[DeployDatastore]) -> tuple[IRDeployProcess, ...]:
    processes = deploy.backend.processes
    if clash := sorted({process.name for process in processes} & {ds.service for ds in datastores}):
        raise ValueError(f"deploy processes {clash} clash with datastore services of the same name")
    return processes


def _package(source: Path) -> DeployPackage:
    requirements = sorted(path.relative_to(source).as_posix() for path in source.rglob("requirements.txt"))
    return DeployPackage(source=source, requirements=tuple(requirements))


def _frontend_source(frontend: IRDeployFrontend, spec_dir: Path) -> DeployFrontendSource | None:
    if frontend.source is None:
        return None
    source = (spec_dir / frontend.source).resolve()
    return DeployFrontendSource(
        source=source,
        build=frontend.build,
        output=frontend.output,
        env=frontend.env,
        args=frontend.args,
        secrets=frontend.secrets,
        locked=(source / "package-lock.json").is_file(),
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
