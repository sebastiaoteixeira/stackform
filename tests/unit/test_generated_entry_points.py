"""Each generated target started through its own entry point serves on api.port."""

import contextlib
import os
import signal
import socket
import subprocess
import sys
import time

import httpx
import pytest

from tests.unit.support.generated_apps import generate, write_spec

ENTRY_POINTS = {
    "fastapi": ["app.py"],
    "raw": ["app.py"],
    "drf": ["manage.py", "runserver", "--noreload"],
}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _first_response(port: int, server: subprocess.Popen, timeout: float = 30) -> httpx.Response:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and server.poll() is None:
        with contextlib.suppress(httpx.TransportError):
            return httpx.get(f"http://127.0.0.1:{port}/api/missing", timeout=2)
        time.sleep(0.2)
    raise AssertionError(f"nothing answered on port {port}")


@pytest.mark.parametrize("target", ENTRY_POINTS)
def test_entry_point_serves_api_port(tmp_path, target):
    port = _free_port()
    spec = write_spec(tmp_path, f"""
        version: "0.3"
        api: {{ basePath: /api, port: {port} }}
        mongo: {{ uri: "mongodb://localhost:27017", database: app }}
        entities:
          post: {{ fields: {{ id: {{ type: id }}, title: {{ type: string }} }} }}
        repositories: {{ posts: {{ entity: post }} }}
        services: {{ posts: {{ repository: posts }} }}
        controllers:
          posts:
            base_path: /posts
            routes: {{ list: {{ service: posts, method: GET, path: "", access: public }} }}
    """)
    backend = generate(spec, target)
    server = subprocess.Popen(
        [sys.executable, *ENTRY_POINTS[target]],
        cwd=backend,
        env={**os.environ, "DJANGO_SECRET_KEY": "test-secret", "JWT_SECRET": "test-jwt-secret-0123456789abcdef0123456789"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        assert _first_response(port, server).status_code == 404
    finally:
        os.killpg(server.pid, signal.SIGTERM)
        server.wait(10)
