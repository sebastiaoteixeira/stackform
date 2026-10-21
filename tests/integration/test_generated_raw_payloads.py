"""A generated raw-ASGI app validates the shared payload scenario against a real MongoDB."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from tests.unit.support.payload_requests import EXPECTED, JWT_SECRET, MONGO_STORE, spec
from yaml_api_generator.cli.compiler import compile_project


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


@pytest.mark.integration
def test_generated_raw_validates_payloads(tmp_path, mongo_uri):
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(spec(MONGO_STORE))
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
