"""Soft deletion and expiry on MongoDB: over HTTP on the dev server and generated apps, and in generated repositories."""

import compileall
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pymongo import MongoClient

from tests.integration.support.spec_apps import MONGO_BACKENDS, serve
from tests.support.lifecycle import EXPIRED, VERSIONS, MongoNotes, exercise_declared_deletes, mongo_spec, verify
from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.runtime.mongo_lifecycle import EXPIRY_INDEX

pytestmark = pytest.mark.integration

V01_SPEC = """
version: "0.1"
api:
  operations:
    defaults: { list: true, get: true, create: true, update: true, replace: true, delete: true }
collections:
  notes:
    fields:
      id: { type: id }
      title: { type: string, required: true }
    softDelete: true
    access: { list: public, get: public, create: public, update: public, replace: public, delete: public }
"""


@pytest.fixture(scope="module")
def ttl_monitor(mongo_uri):
    """The TTL monitor sweeping every second instead of every minute."""
    with MongoClient(mongo_uri) as client:
        previous = client.admin.command("setParameter", 1, ttlMonitorSleepSecs=1)["was"]
        yield
        client.admin.command("setParameter", 1, ttlMonitorSleepSecs=previous)


def _spec(tmp_path: Path, text: str) -> Path:
    spec = tmp_path / "notes.yaml"
    spec.write_text(text)
    return spec


def _database(mongo_uri: str) -> tuple[str, dict[str, str]]:
    database = f"notes_{uuid4().hex[:12]}"
    env = {"MONGO_URI": mongo_uri, "MONGO_DB": database, "YAML_API_MONGO_URI": mongo_uri, "YAML_API_MONGO_DB": database}
    return database, env


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("backend", MONGO_BACKENDS, ids=lambda backend: backend.name)
def test_removed_and_expired_notes(tmp_path, mongo_uri, ttl_monitor, backend, version):
    spec, (database, env) = _spec(tmp_path, mongo_spec(version=version)), _database(mongo_uri)
    verify(lambda: serve(backend, spec, env), MongoNotes(mongo_uri, database), exercise_declared_deletes)
    with MongoClient(mongo_uri) as client:
        index = client[database]["notes"].index_information()[EXPIRY_INDEX]
    assert (index["key"], index["expireAfterSeconds"]) == ([("createdAt", 1)], 3600)


@pytest.mark.parametrize("backend", MONGO_BACKENDS, ids=lambda backend: backend.name)
def test_v01_soft_delete(tmp_path, mongo_uri, backend):
    spec, (database, env) = _spec(tmp_path, V01_SPEC), _database(mongo_uri)
    with serve(backend, spec, env) as client:
        ids = [client.post("/api/notes", json={"title": title}).json()["id"] for title in ("kept", "removed")]
        assert client.delete(f"/api/notes/{ids[1]}").status_code in (200, 204)
        assert client.get(f"/api/notes/{ids[1]}").status_code == 404
        assert [note["title"] for note in client.get("/api/notes").json()] == ["kept"]
    assert MongoNotes(mongo_uri, database).rows() == {"kept": False, "removed": True}


def _build(spec: Path, target: str) -> Path:
    output = spec.parent / target
    compile_project(yaml_file=str(spec), output_dir=str(output), target=target)
    return output / "backend"


_QUERY_OPERATIONS = """
import asyncio, json, sys
from pymongo import AsyncMongoClient
from api.repositories.notes import NotesRepository

async def main():
    repository = NotesRepository(AsyncMongoClient(sys.argv[1])[sys.argv[2]])
    print(json.dumps({name: sorted(row["title"] for row in await getattr(repository, name)({})) for name in sys.argv[3:]}))

asyncio.run(main())
"""


@pytest.mark.parametrize("version", VERSIONS)
def test_drf_custom_operations_honour_include_deleted(tmp_path, mongo_uri, version):
    """Drives the DRF repository directly, covering it where no interpreter holds the DRF requirements."""
    database, _ = _database(mongo_uri)
    with MongoClient(mongo_uri) as client:
        client[database]["notes"].insert_many([
            {"title": "kept", "createdAt": datetime.now(UTC)},
            {"title": "removed", "deletedAt": datetime.now(UTC).isoformat()},
            {"title": "expired", "createdAt": datetime.fromisoformat(EXPIRED).replace(tzinfo=UTC)},
        ])
    backend = _build(_spec(tmp_path, mongo_spec(version=version)), "drf")
    assert compileall.compile_dir(str(backend), quiet=1)
    result = subprocess.run(
        [sys.executable, "-c", _QUERY_OPERATIONS, mongo_uri, database, "everything", "current"],
        cwd=backend, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"everything": ["expired", "kept", "removed"], "current": ["kept"]}
