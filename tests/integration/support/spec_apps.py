"""A spec served over real HTTP by `stackform run` and by each backend it generates."""

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

from .network import free_port, wait_until

STACKFORM = str(Path(sys.executable).with_name("stackform"))


@dataclass(frozen=True)
class Backend:
    """`stackform run` when `target` is None, otherwise the app `stackform build` emits for `target`."""

    name: str
    target: str | None = None

    def command(self, spec: Path, env: dict[str, str], port: int) -> tuple[list[str], Path]:
        if self.target is None:
            return [STACKFORM, "run", str(spec), "--port", str(port)], spec.parent
        output = spec.parent / self.target
        subprocess.run(
            [STACKFORM, "build", str(spec), "backend", "--target", self.target, "--output", str(output)],
            env=env, check=True, capture_output=True,
        )
        return [sys.executable, "-m", "uvicorn", "app:app", "--port", str(port)], output / "backend"


DEV = Backend("run")
FASTAPI = Backend("fastapi", "fastapi")
RAW = Backend("raw", "raw")

SQL_BACKENDS = (DEV, FASTAPI)
MONGO_BACKENDS = (DEV, FASTAPI, RAW)


def _answering(url: str) -> bool:
    try:
        httpx.get(url, timeout=1)
        return True
    except httpx.HTTPError:
        return False


@contextmanager
def serve(backend: Backend, spec: Path, env: dict[str, str] | None = None) -> Iterator[httpx.Client]:
    """Serve `spec` with `backend` and yield a client bound to its root URL."""
    environment = {**os.environ, "JWT_SECRET": "spec-apps-secret", **(env or {})}
    port = free_port()
    command, cwd = backend.command(spec, environment, port)
    url, log = f"http://127.0.0.1:{port}", spec.parent / f"{backend.name}.log"
    with log.open("wb") as output:
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=output, stderr=subprocess.STDOUT)
        try:
            if not wait_until(lambda: process.poll() is not None or _answering(url)) or process.poll() is not None:
                raise RuntimeError(f"{backend.name} server did not start:\n{log.read_text()}")
            with httpx.Client(base_url=url, timeout=30) as client:
                yield client
        finally:
            process.terminate()
            process.wait(timeout=10)
