"""Compile a spec for a backend target and drive the generated app over HTTP."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

from yaml_api_generator.cli.compiler import compile_project

_REPOSITORY = Path(__file__).parents[3]

_PRELUDE = """
import json
from starlette.testclient import TestClient
import app

client = TestClient(app.app)
"""


def write_spec(directory: Path, spec: str) -> Path:
    path = directory / "spec.yaml"
    path.write_text(textwrap.dedent(spec))
    return path


def generate(spec: Path, target: str) -> Path:
    compile_project(yaml_file=spec, output_dir=spec.parent / target, target=target)
    return spec.parent / target / "backend"


def run_generated(spec: Path, target: str, script: str, env: dict[str, str] | None = None) -> Any:
    """Run ``script`` against ``client``, a TestClient of the generated app, and return what it prints as JSON.

    The script can import the ``tests`` package, so probes are shared with in-process tests.
    """
    result = subprocess.run(
        [sys.executable, "-c", _PRELUDE + textwrap.dedent(script)],
        cwd=generate(spec, target),
        env={**os.environ, "PYTHONPATH": str(_REPOSITORY), **(env or {})},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])
