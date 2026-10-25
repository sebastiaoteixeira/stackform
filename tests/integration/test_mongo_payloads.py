"""Development servers and generated raw-ASGI and DRF apps validate the shared payload scenario against a real MongoDB."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from starlette.testclient import TestClient

from tests.unit.support.payload_requests import EXPECTED, JWT_SECRET, mongo_store, scenario, spec
from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.server import build_app, build_raw_app


ROOT = Path(__file__).parents[2]

_RUNNER = f"""
import json, sys
sys.path.append({str(ROOT)!r})
from starlette.testclient import TestClient
from tests.unit.support.payload_requests import scenario
import app

with TestClient(app.app) as client:
    print(json.dumps(scenario(client)))
"""


DRF_PYTHON = os.environ.get("YAML_API_TEST_DRF_PYTHON")
"""An interpreter with the generated DRF requirements installed."""


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _scenario_env(mongo_uri: str) -> dict[str, str]:
    return {
        **os.environ,
        "MONGO_URI": mongo_uri,
        "MONGO_DB": f"payloads_{uuid4().hex}",
        "JWT_SECRET": JWT_SECRET,
        "PASSWORD_HASH_ROUNDS": "1000",
    }


@pytest.fixture
def spec_file(tmp_path, mongo_uri):
    path = tmp_path / "spec.yaml"
    path.write_text(spec(mongo_store(mongo_uri, f"payloads_{uuid4().hex}")))
    return path


@pytest.mark.integration
@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["fastapi", "raw"])
def test_dev_server_validates_payloads(spec_file, build, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    with TestClient(build(str(spec_file))) as client:
        assert scenario(client) == EXPECTED


@pytest.mark.integration
def test_generated_raw_validates_payloads(spec_file, tmp_path, mongo_uri):
    compile_project(yaml_file=str(spec_file), output_dir=str(tmp_path / "raw"), target="raw")
    result = subprocess.run(
        [sys.executable, "-c", _RUNNER],
        cwd=tmp_path / "raw" / "backend",
        env=_scenario_env(mongo_uri),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == EXPECTED


@pytest.mark.integration
@pytest.mark.skipif(DRF_PYTHON is None, reason="YAML_API_TEST_DRF_PYTHON is not set")
def test_generated_drf_validates_payloads(spec_file, tmp_path, mongo_uri):
    compile_project(yaml_file=str(spec_file), output_dir=str(tmp_path / "drf"), target="drf")
    port = _free_port()
    server = subprocess.Popen(
        [DRF_PYTHON, "-m", "uvicorn", "project.asgi:application", "--port", str(port)],
        cwd=tmp_path / "drf" / "backend",
        env={**_scenario_env(mongo_uri), "DJANGO_SECRET_KEY": "payload-scenario-django-key"},
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            deadline = time.monotonic() + 30
            while not _serves(client) and time.monotonic() < deadline:
                assert server.poll() is None, "DRF server exited"
                time.sleep(0.2)
            assert scenario(client) == EXPECTED
    finally:
        server.terminate()
        server.wait()


def _serves(client: httpx.Client) -> bool:
    try:
        client.get("/schema")
    except httpx.TransportError:
        return False
    return True
