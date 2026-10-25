"""Runs a request scenario against a generated backend in its own interpreter, where its modules import."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3]

_RUNNER = """
import json, sys
sys.path.append({root!r})
from starlette.testclient import TestClient
from {module} import scenario
import app

with TestClient(app.app) as client:
    print(json.dumps(scenario(client)))
"""


def run_generated(backend: Path, module: str, env: dict[str, str]) -> list:
    """What `module.scenario` returns when run against the `app` in `backend`."""
    result = subprocess.run(
        [sys.executable, "-c", _RUNNER.format(root=str(ROOT), module=module)],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])
