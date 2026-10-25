"""Serve a spec over real HTTP from the development server and from the backends it generates."""

import os
import subprocess
import sys
import textwrap
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from tests.integration.support.network import free_port, wait_until
from yaml_api_generator.cli.compiler import compile_project

STACKFORM = str(Path(sys.executable).with_name("stackform"))


class Server(ABC):
    """How one consumer turns a spec into a process listening on `port`."""

    name: str
    environment: dict[str, str] = {}

    @abstractmethod
    def command(self, spec: Path, port: int) -> tuple[list[str], Path]: ...


class DevServer(Server):
    name = "dev"

    def command(self, spec, port):
        return [STACKFORM, "run", str(spec), "--port", str(port)], spec.parent


class GeneratedApp(Server):
    """The backend generated for one target, served by its own process."""

    def __init__(self, target: str) -> None:
        self.name = target

    def command(self, spec, port):
        output = spec.parent / "generated"
        compile_project(yaml_file=spec, output_dir=output, target=self.name)
        return self.process(port), output / "backend"

    def process(self, port: int) -> list[str]:
        return [sys.executable, "-m", "uvicorn", "app:app", "--port", str(port)]


class DjangoApp(GeneratedApp):
    """The generated DRF backend under uvicorn, run by the interpreter YAML_API_TEST_DRF_PYTHON names; skipped without one."""

    environment = {"DJANGO_SECRET_KEY": "test", "JWT_SECRET": "test"}

    def __init__(self) -> None:
        super().__init__("drf")

    def process(self, port):
        python = os.environ.get("YAML_API_TEST_DRF_PYTHON")
        if python is None:
            pytest.skip("YAML_API_TEST_DRF_PYTHON is not set")
        return [python, "-m", "uvicorn", "project.asgi:application", "--port", str(port)]


SERVERS = (DevServer(), GeneratedApp("fastapi"))
MONGO_SERVERS = (*SERVERS, GeneratedApp("raw"), DjangoApp())


def sqlite(directory: Path) -> str:
    return f'datastores:\n  store: {{ type: postgres, dsn: "sqlite+aiosqlite:///{directory / "store.sqlite"}", default: true }}'


def mongo(uri: str, database: str) -> str:
    return f'mongo: {{ uri: "{uri}", database: {database} }}'


def write_spec(directory: Path, spec: str, datastore: str | None = None) -> Path:
    """Write `spec`, whose `{datastore}` line becomes `datastore`, a SQLite file beside it by default."""
    path = directory / "spec.yaml"
    path.write_text(textwrap.dedent(spec).replace("{datastore}", datastore or sqlite(directory)))
    return path


def _serving(url: str) -> bool:
    try:
        httpx.get(url, timeout=1)
        return True
    except httpx.HTTPError:
        return False


@contextmanager
def serve(server: Server, spec: Path, env: dict[str, str] | None = None) -> Iterator[httpx.Client]:
    port = free_port()
    command, cwd = server.command(spec, port)
    url, log = f"http://127.0.0.1:{port}", spec.parent / f"{server.name}.log"
    with log.open("wb") as output:
        process = subprocess.Popen(
            command, cwd=cwd, env={**os.environ, **server.environment, **(env or {})}, stdout=output, stderr=subprocess.STDOUT
        )
        try:
            if not wait_until(lambda: process.poll() is not None or _serving(url)) or process.poll() is not None:
                raise RuntimeError(f"{server.name} server did not start:\n{log.read_text()}")
            with httpx.Client(base_url=url, timeout=30) as client:
                yield client
        finally:
            process.terminate()
            process.wait(timeout=10)
