from ...ir import IRDocument
from .context import DeployContext, DockerDeployContext, SystemdDeployContext


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
    )

    if deploy.runtime == "docker":
        image = deploy.docker.image if deploy.docker else None
        return DockerDeployContext(
            **common,
            image=image,
            extra_services=deploy.extra_services,
            include=deploy.include,
        )

    if deploy.runtime == "systemd":
        sd = deploy.systemd
        return SystemdDeployContext(
            **common,
            user=sd.user if sd else "ubuntu",
            restart=sd.restart if sd else "on-failure",
        )

    raise ValueError(f"unknown runtime: {deploy.runtime}")