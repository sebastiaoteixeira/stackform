"""Soft deletion and expiry over HTTP on a SQL datastore, served by the dev server and by a generated FastAPI app."""

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from tests.support.lifecycle import SQL_SPEC, SqliteNotes, exercise_archive, verify
from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.server import build_raw_app

ROOT = Path(__file__).parents[2]


def _spec(tmp_path: Path) -> Path:
    spec = tmp_path / "notes.yaml"
    spec.write_text(SQL_SPEC)
    return spec


def test_dev_server(tmp_path, monkeypatch):
    database = str(tmp_path / "notes.sqlite")
    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{database}")
    spec = str(_spec(tmp_path))
    verify(lambda: TestClient(build_raw_app(spec)), SqliteNotes(database), exercise_archive)


def test_generated_fastapi(tmp_path):
    compile_project(yaml_file=str(_spec(tmp_path)), output_dir=str(tmp_path), target="fastapi")
    database = str(tmp_path / "notes.sqlite")
    script = (
        "import app\n"
        "from fastapi.testclient import TestClient\n"
        "from tests.support.lifecycle import SqliteNotes, verify\n"
        f"verify(lambda: TestClient(app.app), SqliteNotes({database!r}))\n"
    )
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{database}",
        "PYTHONPATH": os.pathsep.join(filter(None, (str(ROOT), os.environ.get("PYTHONPATH")))),
    }
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path / "backend", env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
