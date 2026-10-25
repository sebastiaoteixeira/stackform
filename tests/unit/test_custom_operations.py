"""Custom (non-CRUD) operations executed as pipeline steps.

Covers the shared binding resolver, a Postgres `sql:` operation end-to-end over
HTTP (SQLite-backed run server), and a MongoDB command operation against a fake
collection.
"""

import json
import textwrap

import pytest

from yaml_api_generator.server import build_raw_app
from yaml_api_generator.runtime.operations import resolve
from yaml_api_generator.server.common.repositories.mongodb import (
    MongoRepository,
    MongoRepositoryConfig,
)


def test_resolve_substitutes_dotted_refs():
    bindings = {"principal": {"id": "u1"}, "params": {"slug": "x"}, "body": {}}
    assert resolve("$principal.id", bindings) == "u1"
    assert resolve({"author": "$principal.id", "lit": 3}, bindings) == {"author": "u1", "lit": 3}
    assert resolve(["$params.slug", "plain"], bindings) == ["x", "plain"]
    assert resolve("$missing.key", bindings) is None


_SQL_SPEC = """
    version: "0.2"
    api: { basePath: "" }
    datastores:
      store: { type: postgres, dsn: "postgresql+asyncpg://localhost/x", default: true }
    entities:
      task:
        fields:
          id: { type: id }
          title: { type: string, required: true }
    repositories:
      tasks:
        entity: task
        operations:
          byTitle:
            query:
              sql: "SELECT * FROM tasks WHERE title = :title"
              params: { title: "$params.title" }
    services:
      tasks: { repository: tasks }
      byTitle: { repository: tasks, operation: byTitle }
    controllers:
      tasks:
        base_path: /tasks
        routes:
          create:  { service: tasks, method: POST, path: "", access: public }
          byTitle: { service: byTitle, method: GET, path: "/by-title/{title}", access: public }
"""


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
async def test_sql_custom_operation_over_http(tmp_path, monkeypatch):
    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path/'db.sqlite'}")
    spec = tmp_path / "spec.yaml"
    spec.write_text(textwrap.dedent(_SQL_SPEC))
    app = build_raw_app(str(spec))

    await _invoke(app, "POST", "/tasks", {"title": "alpha"})
    await _invoke(app, "POST", "/tasks", {"title": "beta"})

    status, rows = await _invoke(app, "GET", "/tasks/by-title/alpha")
    assert status == 200
    assert [r["title"] for r in rows] == ["alpha"]


class _FakeCursor:
    def __init__(self, docs):
        self._docs = iter(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._docs)
        except StopIteration:
            raise StopAsyncIteration from None


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs
        self.received_filter = None

    def find(self, query_filter):
        self.received_filter = query_filter
        return _FakeCursor(
            [d for d in self._docs if all(d.get(k) == v for k, v in query_filter.items())]
        )


@pytest.mark.asyncio
async def test_mongo_find_operation_runs_resolved_query():
    repo = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="d"))
    collection = _FakeCollection([
        {"_id": "1", "authorId": "u1", "title": "mine"},
        {"_id": "2", "authorId": "u2", "title": "theirs"},
    ])
    repo._db = {"posts": collection}

    bindings = {"principal": {"id": "u1"}, "params": {}, "body": {}}
    query = resolve({"command": "find", "filter": {"authorId": "$principal.id"}}, bindings)

    result = await repo.run_operation("posts", query)
    assert collection.received_filter == {"authorId": "u1"}
    assert [d["title"] for d in result] == ["mine"]
    assert all("_id" in d for d in result)
