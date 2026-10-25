"""Soft deletion and expiry on MongoDB: over HTTP on the dev server and generated apps, and in generated repositories."""

import compileall
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pymongo import MongoClient

from tests.integration.support.file_apps import YAML_API
from tests.integration.support.network import free_port, listening
from tests.support.lifecycle import LONG_AGO, MONGO_SPEC, MongoNotes, Scenario, exercise, exercise_archive, verify
from yaml_api_generator.cli.compiler import compile_project

pytestmark = pytest.mark.integration

UVICORN = [sys.executable, "-m", "uvicorn", "app:app"]


def _spec(tmp_path: Path) -> Path:
    spec = tmp_path / "notes.yaml"
    spec.write_text(MONGO_SPEC)
    return spec


def _database() -> str:
    return f"notes_{uuid4().hex[:12]}"


def _dev(spec: Path, port: int) -> tuple[list[str], Path]:
    return [YAML_API, "run", str(spec), "--port", str(port)], spec.parent


def _build(spec: Path, target: str) -> Path:
    output = spec.parent / target
    if not output.exists():
        compile_project(yaml_file=str(spec), output_dir=str(output), target=target)
    return output / "backend"


def _generated(target: str):
    def command(spec: Path, port: int) -> tuple[list[str], Path]:
        return [*UVICORN, "--port", str(port)], _build(spec, target)

    return command


# Generated apps route only CRUD, so the includeDeleted operation is reached over HTTP on the dev server alone.
BACKENDS = {
    "run": (_dev, exercise_archive),
    "fastapi": (_generated("fastapi"), exercise),
    "raw": (_generated("raw"), exercise),
}


@pytest.mark.parametrize(("command", "scenario"), BACKENDS.values(), ids=list(BACKENDS))
def test_removed_and_expired_notes(tmp_path, mongo_uri, command, scenario: Scenario):
    spec, database = _spec(tmp_path), _database()
    env = {**os.environ, "MONGO_URI": mongo_uri, "MONGO_DB": database}

    @contextmanager
    def serve() -> Iterator[httpx.Client]:
        port = free_port()
        argv, cwd = command(spec, port)
        url = f"http://127.0.0.1:{port}"
        with listening(argv, cwd=cwd, env=env, probe=f"{url}/api/notes", log=tmp_path / "server.log"):
            with httpx.Client(base_url=url, timeout=30) as client:
                yield client

    verify(serve, MongoNotes(mongo_uri, database), scenario)


_QUERY_OPERATIONS = """
import asyncio, json, sys
from pymongo import AsyncMongoClient
from {module} import NotesRepository

async def main():
    repository = NotesRepository(AsyncMongoClient(sys.argv[1])[sys.argv[2]])
    print(json.dumps({{name: sorted(row["title"] for row in await getattr(repository, name)({{}})) for name in sys.argv[3:]}}))

asyncio.run(main())
"""

# DRF is not runnable without Django installed, so its repository is driven directly, as are the others for parity.
REPOSITORIES = {"fastapi": "repositories.notes", "raw": "repositories.notes", "drf": "api.repositories.notes"}


@pytest.mark.parametrize(("target", "module"), REPOSITORIES.items(), ids=list(REPOSITORIES))
def test_generated_custom_operations_honour_include_deleted(tmp_path, mongo_uri, target, module):
    database = _database()
    with MongoClient(mongo_uri) as client:
        client[database]["notes"].insert_many([
            {"title": "kept", "createdAt": datetime.now(UTC).isoformat()},
            {"title": "removed", "deletedAt": datetime.now(UTC).isoformat()},
            {"title": "expired", "createdAt": LONG_AGO.isoformat()},
        ])
    backend = _build(_spec(tmp_path), target)
    assert compileall.compile_dir(str(backend), quiet=1)
    result = subprocess.run(
        [sys.executable, "-c", _QUERY_OPERATIONS.format(module=module), mongo_uri, database, "everything", "current"],
        cwd=backend, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"everything": ["expired", "kept", "removed"], "current": ["kept"]}
