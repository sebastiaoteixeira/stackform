"""Unique violations become safe 409 responses across runtime and generated apps.

The relational path runs against in-memory SQLite via aiosqlite. Mongo tests use
the driver's real error types at the repository boundary, including bulk writes.
Generated FastAPI, DRF, and raw-ASGI repositories are compiled, imported, and
executed in subprocesses.
"""

import compileall
import json
import os
import subprocess
import sys
import textwrap
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import BulkWriteError, DuplicateKeyError
from sqlalchemy.exc import IntegrityError

from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.ir import IRCollection
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from yaml_api_generator.server import build_app, build_raw_app
from yaml_api_generator.server.common.repositories import ConflictError
from yaml_api_generator.server.common.repositories.mongodb import (
    MongoRepository,
    MongoRepositoryConfig,
)
from yaml_api_generator.server.common.repositories.sql import SQLRepository


def _collection() -> IRCollection:
    return IRCollection(
        name="members",
        entity_name="member",
        type="base",
        idField="id",
        idFormat="uuidv4",
        fields={
            "id": {"type": "id"},
            "email": {"type": "string", "required": True, "unique": True},
        },
        datastore="warehouse",
    )


@pytest.fixture
async def repo():
    repository = SQLRepository("sqlite+aiosqlite://", [_collection()])
    repository.connect()
    yield repository
    await repository.close()


@pytest.mark.asyncio
async def test_sql_duplicate_create_raises_conflict_naming_field(repo):
    await repo.create("members", {"id": "m1", "email": "a@x.io"})
    with pytest.raises(ConflictError) as excinfo:
        await repo.create("members", {"id": "m2", "email": "a@x.io"})
    assert excinfo.value.field == "email"
    assert "email" in str(excinfo.value)


@pytest.mark.asyncio
async def test_sql_duplicate_update_raises_conflict(repo):
    await repo.create("members", {"id": "m1", "email": "a@x.io"})
    await repo.create("members", {"id": "m2", "email": "b@x.io"})
    with pytest.raises(ConflictError) as excinfo:
        await repo.update("members", "m2", {"email": "a@x.io"})
    assert excinfo.value.field == "email"


@pytest.mark.asyncio
async def test_sql_duplicate_update_by_raises_conflict(repo):
    await repo.create("members", {"id": "m1", "email": "a@x.io"})
    await repo.create("members", {"id": "m2", "email": "b@x.io"})
    with pytest.raises(ConflictError) as excinfo:
        await repo.update_by("members", {"id": "m2"}, {"email": "a@x.io"})
    assert excinfo.value.field == "email"


@pytest.mark.asyncio
async def test_sql_duplicate_replace_by_raises_conflict(repo):
    await repo.create("members", {"id": "m1", "email": "a@x.io"})
    await repo.create("members", {"id": "m2", "email": "b@x.io"})
    with pytest.raises(ConflictError) as excinfo:
        await repo.replace_by("members", {"id": "m2"}, {"email": "a@x.io"})
    assert excinfo.value.field == "email"


@pytest.mark.asyncio
async def test_sql_custom_write_duplicate_raises_conflict(repo):
    await repo.create("members", {"id": "m1", "email": "a@x.io"})
    await repo.create("members", {"id": "m2", "email": "b@x.io"})
    with pytest.raises(ConflictError) as excinfo:
        await repo.run_operation(
            "members",
            {
                "sql": "UPDATE members SET email = :email WHERE id = :id",
                "params": {"email": "a@x.io", "id": "m2"},
            },
        )
    assert excinfo.value.field == "email"


@pytest.mark.asyncio
async def test_sql_non_unique_integrity_error_is_not_mapped_to_conflict(repo):
    with pytest.raises(IntegrityError):
        await repo.create("members", {"id": "m1", "email": None})


class _DuplicateCollection:
    @staticmethod
    def _error() -> DuplicateKeyError:
        return DuplicateKeyError(
            "E11000 duplicate key error",
            details={"keyPattern": {"email": 1}, "keyValue": {"email": "a@x.io"}},
        )

    async def insert_one(self, payload: dict[str, Any]) -> Any:
        raise self._error()

    async def insert_many(self, payload: list[dict[str, Any]]) -> Any:
        raise self._error()

    async def find_one_and_update(self, *args, **kwargs) -> Any:
        raise self._error()

    async def find_one_and_replace(self, *args, **kwargs) -> Any:
        raise self._error()

    async def update_many(self, *args, **kwargs) -> Any:
        raise self._error()

    async def bulk_write(self, *args, **kwargs) -> Any:
        raise self._error()


class _BulkDuplicateCollection(_DuplicateCollection):
    async def insert_many(self, payload: list[dict[str, Any]]) -> Any:
        raise BulkWriteError(
            {
                "writeErrors": [
                    {
                        "code": 11000,
                        "keyPattern": {"email": 1},
                        "keyValue": {"email": "a@x.io"},
                    }
                ]
            }
        )


class _NonDuplicateBulkCollection(_DuplicateCollection):
    async def insert_many(self, payload: list[dict[str, Any]]) -> Any:
        raise BulkWriteError({"writeErrors": [{"code": 121}]})


@pytest.mark.asyncio
async def test_mongo_duplicate_key_raises_conflict_naming_field():
    repository = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
    repository._db = {"members": _DuplicateCollection()}
    with pytest.raises(ConflictError) as excinfo:
        await repository.create("members", {"id": "m1", "email": "a@x.io"})
    assert excinfo.value.field == "email"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [
        lambda repository: repository.update_by(
            "members", {"id": "m1"}, {"email": "a@x.io"}
        ),
        lambda repository: repository.replace_by(
            "members", {"id": "m1"}, {"email": "a@x.io"}
        ),
        lambda repository: repository.update(
            "members", "m1", {"email": "a@x.io"}
        ),
        lambda repository: repository.replace(
            "members", "m1", {"email": "a@x.io"}
        ),
        lambda repository: repository.upsert_by(
            "members", "email", {"email": "a@x.io"}
        ),
        lambda repository: repository.run_operation(
            "members",
            {"command": "insertOne", "document": {"email": "a@x.io"}},
        ),
    ],
)
async def test_mongo_all_unique_write_paths_raise_conflict(operation):
    repository = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
    repository._db = {"members": _DuplicateCollection()}

    with pytest.raises(ConflictError) as excinfo:
        await operation(repository)

    assert excinfo.value.field == "email"


@pytest.mark.asyncio
async def test_mongo_bulk_duplicate_raises_conflict_naming_field():
    repository = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
    repository._db = {"members": _BulkDuplicateCollection()}

    with pytest.raises(ConflictError) as excinfo:
        await repository.run_operation(
            "members",
            {"command": "insertMany", "documents": [{"email": "a@x.io"}]},
        )

    assert excinfo.value.field == "email"


@pytest.mark.asyncio
async def test_mongo_non_duplicate_bulk_error_is_not_mapped_to_conflict():
    repository = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
    repository._db = {"members": _NonDuplicateBulkCollection()}

    with pytest.raises(BulkWriteError):
        await repository.run_operation(
            "members",
            {"command": "insertMany", "documents": [{"email": "a@x.io"}]},
        )


_SPEC = """
    version: "0.2"
    api: { basePath: "" }
    datastores:
      store:
        type: postgres
        dsn: "postgresql+asyncpg://localhost/unused"
        default: true
    entities:
      member:
        fields:
          id: { type: id, format: uuidv4 }
          email: { type: string, required: true, unique: true }
    repositories:
      members: { entity: member }
    services:
      members: { repository: members }
    controllers:
      members:
        base_path: /members
        routes:
          create: { service: members, method: POST, path: "", access: public }
          update: { service: members, method: PATCH, path: "/{id}", access: public }
"""

_MONGO_SPEC = """
    version: "0.3"
    api: { basePath: "" }
    mongo: { uri: "mongodb://localhost:27017", database: testdb }
    entities:
      member:
        fields:
          id: { type: id, format: uuidv4 }
          email: { type: string, required: true, unique: true }
    repositories:
      members:
        entity: member
        operations:
          insertBatch:
            query:
              command: insertMany
              documents: [{ email: "a@x.io" }]
    services:
      members: { repository: members }
      notify: { handler: app.handlers.notify }
    controllers:
      members:
        base_path: /members
        routes:
          create: { service: members, method: POST, path: "", access: public }
          notify: { service: notify, method: POST, path: /notify, access: public }
"""


def _write_spec(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(textwrap.dedent(_SPEC))
    return str(spec)


def _mongo_context(tmp_path):
    spec = tmp_path / "mongo-spec.yaml"
    spec.write_text(textwrap.dedent(_MONGO_SPEC))
    return build_context(load_and_generate_ir(str(spec)).ir)


async def _invoke(app, method, path, body=None):
    scope = {"type": "http", "method": method, "path": path, "headers": []}

    async def receive():
        payload = json.dumps(body).encode() if body is not None else b""
        return {"type": "http.request", "body": payload, "more_body": False}

    messages = []

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    data = next(m for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(data["body"])


@pytest.mark.asyncio
async def test_raw_asgi_duplicate_returns_409(tmp_path, monkeypatch):
    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path/'db.sqlite'}")
    app = build_raw_app(_write_spec(tmp_path))
    status, _ = await _invoke(app, "POST", "/members", {"email": "a@x.io"})
    assert status == 200
    status, body = await _invoke(app, "POST", "/members", {"email": "a@x.io"})
    assert status == 409
    assert "email" in body["detail"]


def test_fastapi_duplicate_returns_409(tmp_path, monkeypatch):
    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path/'db.sqlite'}")
    app = build_app(_write_spec(tmp_path))
    with TestClient(app) as client:
        assert client.post("/members", json={"email": "a@x.io"}).status_code == 200
        response = client.post("/members", json={"email": "a@x.io"})
    assert response.status_code == 409
    assert "email" in response.json()["detail"]


def test_generated_sql_backend_returns_409_for_create_and_update(tmp_path):
    compile_project(
        yaml_file=_write_spec(tmp_path),
        output_dir=str(tmp_path / "generated"),
        target="fastapi",
    )
    backend = tmp_path / "generated" / "backend"
    assert compileall.compile_dir(str(backend), quiet=1)
    script = textwrap.dedent(
        """
        from fastapi.testclient import TestClient
        import app as app_module

        with TestClient(app_module.app) as client:
            first = client.post("/members", json={"email": "a@x.io"})
            assert first.status_code == 200, first.text

            duplicate = client.post("/members", json={"email": "a@x.io"})
            assert duplicate.status_code == 409, duplicate.text
            assert "email" in duplicate.json()["detail"]

            second = client.post("/members", json={"email": "b@x.io"})
            assert second.status_code == 200, second.text
            conflict = client.patch(
                f"/members/{second.json()['id']}",
                json={"email": "a@x.io"},
            )
            assert conflict.status_code == 409, conflict.text
            assert "email" in conflict.json()["detail"]
        """
    )
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'generated.sqlite'}",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("generator", "repository_module", "exception_module", "response_path", "marker"),
    [
        (
            FastAPIGenerator(),
            "repositories.members",
            "conflicts",
            "app.py",
            "status_code=409",
        ),
        (
            DRFGenerator(),
            "api.repositories.members",
            "api.conflicts",
            "api/views/members.py",
            "HTTP_409_CONFLICT",
        ),
        (
            RawASGIGenerator(),
            "repositories.members",
            "conflicts",
            "app.py",
            "_send_json(send, 409",
        ),
    ],
)
def test_generated_mongo_backends_translate_driver_conflicts(
    generator,
    repository_module,
    exception_module,
    response_path,
    marker,
    tmp_path,
):
    output = tmp_path / generator.__class__.__name__
    generator.generate(_mongo_context(tmp_path), output)
    assert compileall.compile_dir(str(output), quiet=1)
    assert marker in (output / response_path).read_text()
    handler_view = output / "api/views/_handlers.py"
    if handler_view.exists():
        handler_source = handler_view.read_text()
        assert "from api.conflicts import ConflictError" in handler_source
        assert "from api.services.exceptions import ConflictError" not in handler_source
    script = textwrap.dedent(
        f"""
        import asyncio
        import importlib

        from pymongo.errors import BulkWriteError, DuplicateKeyError

        repository_module = importlib.import_module({repository_module!r})
        exception_module = importlib.import_module({exception_module!r})

        class Collection:
            async def insert_one(self, document):
                raise DuplicateKeyError(
                    "E11000 duplicate key error",
                    details={{"keyValue": {{"email": document["email"]}}}},
                )

            async def insert_many(self, documents):
                raise BulkWriteError(
                    {{
                        "writeErrors": [
                            {{
                                "code": 11000,
                                "keyValue": {{"email": documents[0]["email"]}},
                            }}
                        ]
                    }}
                )

        repository = repository_module.MembersRepository({{"members": Collection()}})

        async def verify():
            try:
                await repository.create({{"email": "a@x.io"}})
            except exception_module.ConflictError as error:
                assert error.field == "email"
            else:
                raise AssertionError("duplicate key was not translated")

            try:
                await repository.insertBatch([{{"email": "a@x.io"}}])
            except exception_module.ConflictError as error:
                assert error.field == "email"
            else:
                raise AssertionError("bulk duplicate key was not translated")

        asyncio.run(verify())
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=output,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
