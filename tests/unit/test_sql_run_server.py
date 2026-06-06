"""End-to-end run-server test over a SQL-backed datastore.

Drives the raw ASGI app built from a spec whose default datastore is Postgres,
with the DSN overridden to a temp-file SQLite database so the full path
(loader -> registry -> pipeline -> SQLRepository) runs without a Postgres server.
"""

import json
import textwrap

import pytest

from yaml_api_generator.server import build_raw_app


_SPEC = """
    version: "0.2"
    api: { basePath: "" }
    datastores:
      store:
        type: postgres
        dsn: "postgresql+asyncpg://localhost/unused"
        default: true
    entities:
      task:
        fields:
          id: { type: id }
          title: { type: string, required: true }
          done: { type: boolean }
    repositories:
      tasks: { entity: task }
    services:
      tasks: { repository: tasks }
    controllers:
      tasks:
        base_path: /tasks
        routes:
          create: { service: tasks, method: POST, path: "", access: public }
          list:   { service: tasks, method: GET, path: "", access: public }
          get:    { service: tasks, method: GET, path: "/{id}", access: public }
          delete: { service: tasks, method: DELETE, path: "/{id}", access: public }
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


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path/'db.sqlite'}")
    spec = tmp_path / "spec.yaml"
    spec.write_text(textwrap.dedent(_SPEC))
    return build_raw_app(str(spec))


@pytest.mark.asyncio
async def test_sql_crud_over_http(app):
    status, created = await _invoke(app, "POST", "/tasks", {"title": "write tests", "done": False})
    assert status == 200
    task_id = created["id"]
    assert created["title"] == "write tests"

    status, listed = await _invoke(app, "GET", "/tasks")
    assert status == 200 and len(listed) == 1

    status, fetched = await _invoke(app, "GET", f"/tasks/{task_id}")
    assert status == 200 and fetched["id"] == task_id

    status, _ = await _invoke(app, "DELETE", f"/tasks/{task_id}")
    assert status == 200

    status, listed = await _invoke(app, "GET", "/tasks")
    assert status == 200 and listed == []
