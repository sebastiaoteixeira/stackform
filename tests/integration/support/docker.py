"""Throwaway service containers: an endpoint from the environment when set, otherwise a fresh container."""

import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from .network import free_port, wait_until


def docker_available() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(
        ["docker", "info"], capture_output=True, check=False
    ).returncode == 0


@dataclass(frozen=True)
class Service:
    """A dockerised service reachable at `{scheme}://127.0.0.1:{port}` once `ready` accepts that endpoint."""

    name: str
    image: str
    port: int
    scheme: str
    override: str
    ready: Callable[[str], bool]
    env: dict[str, str] = field(default_factory=dict)
    command: tuple[str, ...] = ()

    @contextmanager
    def endpoint(self) -> Iterator[str]:
        if configured := os.environ.get(self.override):
            if not self.ready(configured):
                pytest.skip(f"{self.image} at {self.override}={configured} is unreachable")
            yield configured
            return
        if not docker_available():
            pytest.skip(f"docker is unavailable and {self.override} is not set")
        with self._container() as endpoint:
            yield endpoint

    @contextmanager
    def _container(self) -> Iterator[str]:
        port, name = free_port(), f"yaml-api-test-{self.name}-{uuid4().hex[:12]}"
        options = [option for key, value in self.env.items() for option in ("--env", f"{key}={value}")]
        started = subprocess.run(
            ["docker", "run", "--detach", "--name", name, "--publish", f"127.0.0.1:{port}:{self.port}",
             *options, self.image, *self.command],
            capture_output=True,
            text=True,
            check=False,
        )
        if started.returncode != 0:
            pytest.skip(f"could not start {self.image}: {started.stderr.strip()}")
        try:
            endpoint = f"{self.scheme}://127.0.0.1:{port}"
            if not wait_until(lambda: self.ready(endpoint)):
                pytest.skip(f"{self.image} container did not become ready")
            yield endpoint
        finally:
            subprocess.run(["docker", "stop", name], capture_output=True, check=False)
            subprocess.run(["docker", "rm", name], capture_output=True, check=False)
