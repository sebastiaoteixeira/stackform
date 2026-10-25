"""The files example served over real HTTP by `stackform run` and by the FastAPI app it generates."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from .apps import BACKENDS, Backend, launched
from .minio import object_keys

SPEC = Path(__file__).parents[3] / "examples" / "v03" / "files" / "spec.yaml"
CLIENT_ID = "files-demo"


@dataclass(frozen=True)
class FileApi:
    """A live app and the stores behind it, observed directly rather than through the app."""

    url: str
    disk: Path
    s3_endpoint: str
    bucket: str

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=f"{self.url}/api", timeout=30)

    def on_disk(self, collection: str, file_id: str) -> bool:
        return (self.disk / collection / file_id).is_file()

    async def in_bucket(self, collection: str, file_id: str) -> bool:
        return f"{collection}/{file_id}" in await object_keys(self.s3_endpoint, self.bucket)

    async def contents(self) -> set[str]:
        """Every file the filesystem store and the bucket hold."""
        on_disk = {str(path.relative_to(self.disk)) for path in self.disk.rglob("*") if path.is_file()}
        return on_disk | set(await object_keys(self.s3_endpoint, self.bucket))


@contextmanager
def serve(
    backend: Backend, workdir: Path, *, discovery_url: str, s3_endpoint: str, mongo_uri: str
) -> Iterator[FileApi]:
    scope, disk = f"files-{uuid4().hex[:12]}", workdir / "disk"
    env = {
        **os.environ,
        "MONGO_URI": mongo_uri,
        "MONGO_DB": scope.replace("-", "_"),
        "FILES_DIR": str(disk),
        "S3_ENDPOINT": s3_endpoint,
        "S3_BUCKET": scope,
        "OIDC_DISCOVERY_URL": discovery_url,
    }
    with launched(backend, SPEC, workdir, env) as url:
        yield FileApi(url, disk, s3_endpoint, scope)
