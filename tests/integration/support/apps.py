"""A spec served over real HTTP by `stackform run` and by the FastAPI app it generates."""

import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .network import free_port, listening

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


@contextmanager
def launched(backend: Backend, spec: Path, workdir: Path, env: dict[str, str]) -> Iterator[str]:
    """The URL of `spec` served by `backend` until the context exits."""
    port = free_port()
    command, cwd = backend.command(spec, workdir, env, port)
    url = f"http://127.0.0.1:{port}"
    with listening(command, cwd=cwd, env=env, probe=f"{url}/openapi.json", log=workdir / "server.log"):
        yield url
