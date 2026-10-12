"""The files example served over real HTTP by `stackform run` and by the FastAPI app it generates."""

import os
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from .minio import object_keys
from .network import free_port, wait_until

SPEC = Path(__file__).parents[3] / "examples" / "v03" / "files" / "spec.yaml"
CLIENT_ID = "files-demo"
YAML_API = str(Path(sys.executable).with_name("stackform"))


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


class Backend(ABC):
    """How one backend turns the spec into a process listening on `port`."""

    name: str

    @abstractmethod
    def command(self, workdir: Path, env: dict[str, str], port: int) -> tuple[list[str], Path]: ...


class RunBackend(Backend):
    name = "run"

    def command(self, workdir, env, port):
        return [YAML_API, "run", str(SPEC), "--port", str(port)], workdir


class GeneratedBackend(Backend):
    name = "generated"

    def command(self, workdir, env, port):
        output = workdir / "generated"
        subprocess.run(
            [YAML_API, "build", str(SPEC), "backend", "--target", "fastapi", "--output", str(output)],
            env=env, check=True, capture_output=True,
        )
        return [sys.executable, "-m", "uvicorn", "app:app", "--port", str(port)], output / "backend"


BACKENDS = (RunBackend(), GeneratedBackend())


def _serving(url: str) -> bool:
    try:
        return httpx.get(f"{url}/openapi.json", timeout=1).is_success
    except httpx.HTTPError:
        return False


@contextmanager
def serve(
    backend: Backend, workdir: Path, *, discovery_url: str, s3_endpoint: str, mongo_uri: str
) -> Iterator[FileApi]:
    scope, disk, port = f"files-{uuid4().hex[:12]}", workdir / "disk", free_port()
    env = {
        **os.environ,
        "MONGO_URI": mongo_uri,
        "MONGO_DB": scope.replace("-", "_"),
        "FILES_DIR": str(disk),
        "S3_ENDPOINT": s3_endpoint,
        "S3_BUCKET": scope,
        "OIDC_DISCOVERY_URL": discovery_url,
    }
    command, cwd = backend.command(workdir, env, port)
    url, log = f"http://127.0.0.1:{port}", workdir / "server.log"
    with log.open("wb") as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            if not wait_until(lambda: process.poll() is not None or _serving(url)) or process.poll() is not None:
                raise RuntimeError(f"{backend.name} server did not start:\n{log.read_text()}")
            yield FileApi(url, disk, s3_endpoint, scope)
        finally:
            process.terminate()
            process.wait(timeout=10)
