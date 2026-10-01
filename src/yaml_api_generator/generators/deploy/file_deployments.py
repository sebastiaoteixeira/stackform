"""How each file datastore of a generated app is provisioned when it is deployed."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ..backend.compile_context import (
    FileStoreDescriptor,
    FilesystemStoreDescriptor,
    S3StoreDescriptor,
)
from .context import DeployDatastore, DeployVolume

FILES_ROOT = "/data/files"
MINIO_IMAGE = "minio/minio"
MINIO_PORT = 9000
MINIO_CREDENTIAL = "minioadmin"


@dataclass(frozen=True)
class FileDeployment:
    """`app_env` is the containerised app's environment; `host_env` is for apps run on the host."""

    app_env: dict[str, str] = field(default_factory=dict)
    host_env: dict[str, str] = field(default_factory=dict)
    datastore: DeployDatastore | None = None
    volume: DeployVolume | None = None


def _filesystem(store: FilesystemStoreDescriptor, service: str) -> FileDeployment:
    mount = f"{FILES_ROOT}/{store.name}"
    return FileDeployment(
        app_env={store.env_name("PATH"): mount},
        host_env={store.env_name("PATH"): store.path},
        volume=DeployVolume(f"files_{store.name}", mount),
    )


def _s3(store: S3StoreDescriptor, service: str) -> FileDeployment:
    if not store.local:
        return FileDeployment()
    keys = {
        "ACCESS_KEY": store.access_key or MINIO_CREDENTIAL,
        "SECRET_KEY": store.secret_key or MINIO_CREDENTIAL,
    }
    shared = lambda key: f"${{{store.env_name(key)}:-{keys[key]}}}"
    return FileDeployment(
        datastore=DeployDatastore(
            service=service,
            type="s3",
            image=MINIO_IMAGE,
            local=True,
            app_env={
                store.env_name("ENDPOINT"): f"http://{service}:{MINIO_PORT}",
                store.env_name("CREATE_BUCKET"): "true",
                **{store.env_name(key): value for key, value in keys.items()},
            },
            service_env={
                "MINIO_ROOT_USER": shared("ACCESS_KEY"),
                "MINIO_ROOT_PASSWORD": shared("SECRET_KEY"),
            },
            volume=f"{service}_data",
            volume_path="/data",
            command="server /data",
        )
    )


_DEPLOYMENTS: dict[type, Callable[..., FileDeployment]] = {
    FilesystemStoreDescriptor: _filesystem,
    S3StoreDescriptor: _s3,
}


def build_file_deployments(stores: Mapping[str, FileStoreDescriptor]) -> tuple[FileDeployment, ...]:
    minio = [store for store in stores.values() if isinstance(store, S3StoreDescriptor) and store.local]
    service = lambda store: "minio" if len(minio) == 1 else f"minio-{store.name}"
    return tuple(_DEPLOYMENTS[type(store)](store, service(store)) for store in stores.values())
