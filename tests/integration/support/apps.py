"""A spec served over real HTTP by `stackform run` and by the FastAPI app it generates."""

import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from .network import free_port, wait_until

STACKFORM = str(Path(sys.executable).with_name("stackform"))


class Backend(ABC):
    """How one backend turns a spec into a process listening on `port`."""

    name: str

    @abstractmethod
    def command(self, spec: Path, workdir: Path, env: dict[str, str], port: int) -> tuple[list[str], Path]: ...


class RunBackend(Backend):
    name = "run"

    def command(self, spec, workdir, env, port):
        return [STACKFORM, "run", str(spec), "--port", str(port)], workdir


class GeneratedBackend(Backend):
    name = "generated"

    def command(self, spec, workdir, env, port):
        output = workdir / "generated"
        subprocess.run(
            [STACKFORM, "build", str(spec), "backend", "--target", "fastapi", "--output", str(output)],
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
def launched(backend: Backend, spec: Path, workdir: Path, env: dict[str, str]) -> Iterator[str]:
    """The URL of `spec` served by `backend` until the context exits."""
    port = free_port()
    command, cwd = backend.command(spec, workdir, env, port)
    url, log = f"http://127.0.0.1:{port}", workdir / "server.log"
    with log.open("wb") as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            if not wait_until(lambda: process.poll() is not None or _serving(url)) or process.poll() is not None:
                raise RuntimeError(f"{backend.name} server did not start:\n{log.read_text()}")
            yield url
        finally:
            process.terminate()
            process.wait(timeout=10)
