"""Soft deletion and expiry over HTTP on SQLite, served by the dev server and by a generated FastAPI app."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.support.lifecycle import VERSIONS, SqliteNotes, sql_spec, verify
from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.server import build_raw_app

ROOT = Path(__file__).parents[2]


def _spec(tmp_path: Path, version: str) -> Path:
    spec = tmp_path / "notes.yaml"
    spec.write_text(sql_spec(version=version))
    return spec


def _environment(monkeypatch, database: str) -> None:
    monkeypatch.setenv("SQL_DSN", f"sqlite+aiosqlite:///{database}")
    monkeypatch.setenv("JWT_SECRET", "lifecycle-secret")


@pytest.mark.parametrize("version", VERSIONS)
def test_dev_server(tmp_path, monkeypatch, version):
    database = str(tmp_path / "notes.sqlite")
    _environment(monkeypatch, database)
    spec = str(_spec(tmp_path, version))
    verify(lambda: TestClient(build_raw_app(spec)), SqliteNotes(database))


@pytest.mark.parametrize("version", VERSIONS)
def test_generated_fastapi(tmp_path, monkeypatch, version):
    database = str(tmp_path / "notes.sqlite")
    _environment(monkeypatch, database)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, (str(ROOT), os.environ.get("PYTHONPATH")))))
    compile_project(yaml_file=str(_spec(tmp_path, version)), output_dir=str(tmp_path), target="fastapi")
    script = (
        "import app\n"
        "from fastapi.testclient import TestClient\n"
        "from tests.support.lifecycle import SqliteNotes, verify\n"
        f"verify(lambda: TestClient(app.app), SqliteNotes({database!r}))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path / "backend", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
