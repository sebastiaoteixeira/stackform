from collections import Counter

from sqlalchemy.engine import make_url

from ...ir import IRDocument, IRMongo, IRPostgres
from ..backend.builders import build_context
from ..backend.builders.settings_builder import build_settings_fields
from .context import DeployContext, DeployDatastore, DockerDeployContext, SystemdDeployContext
from .file_deployments import build_file_deployments


def build_deploy_context(
    ir: IRDocument,
    host: str,
    ssh_user: str,
    ssh_key: str,
) -> DeployContext:
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
        has_frontend=ir.has_ui,
        host=host,
        ssh_user=ssh_user,
        ssh_key=ssh_key,
        datastores=datastores,
    )

    if deploy.runtime == "docker":
        image = deploy.docker.image if deploy.docker else None
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
            image=image,
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
            else _mongo_datastore(service, ds, ir.deploy.mongo_local)
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


def _mongo_datastore(service: str, ds: IRMongo, local: bool) -> DeployDatastore:
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