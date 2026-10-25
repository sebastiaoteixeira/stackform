import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_until(condition: Callable[[], bool], timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.25)
    return False


def _answers(url: str) -> bool:
    try:
        return httpx.get(url, timeout=1).status_code < 500
    except httpx.HTTPError:
        return False


@contextmanager
def listening(command: list[str], *, cwd: Path, env: dict[str, str], probe: str, log: Path) -> Iterator[None]:
    """`command` running in `cwd` for as long as the context lasts, entered once `probe` answers HTTP."""
    with log.open("wb") as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            if not wait_until(lambda: process.poll() is not None or _answers(probe)) or process.poll() is not None:
                raise RuntimeError(f"{command[0]} did not start:\n{log.read_text()}")
            yield
        finally:
            process.terminate()
            process.wait(timeout=10)
