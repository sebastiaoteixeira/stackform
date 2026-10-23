"""Development servers and a generated raw-ASGI app validate the shared payload scenario against a real MongoDB."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

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
        env={
            **os.environ,
            "MONGO_URI": mongo_uri,
            "MONGO_DB": f"payloads_{uuid4().hex}",
            "JWT_SECRET": JWT_SECRET,
            "PASSWORD_HASH_ROUNDS": "1000",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == EXPECTED
