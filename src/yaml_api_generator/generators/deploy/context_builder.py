from collections import Counter

from sqlalchemy.engine import make_url

from ...ir import IRDocument, IRPostgres
from .context import DeployContext, DeployDatastore, DockerDeployContext, SystemdDeployContext


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
    env_vars = list(deploy.env_vars)
    datastores = _build_datastores(ir)

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
        app_environment = tuple(
            f"{key}=${{{key}:-{value}}}"
            for ds in datastores
            for key, value in ds.app_env.items()
        ) + (
            f"PORT=${{PORT:-{deploy.port}}}",
            "FRONTEND_URL=${FRONTEND_URL:-http://localhost}",
        )
        return DockerDeployContext(
            **common,
            image=image,
            extra_services=deploy.extra_services,
            include=deploy.include,
            app_environment=app_environment,
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