"""A soft-deleting, expiring notes API and the HTTP behaviour every backend serving it must show."""

import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

import httpx
import psycopg
from pymongo import MongoClient

from tests.integration.support.network import wait_until

_SPEC = """
version: "0.2"
api:
  basePath: /api
  operations:
    auth: {{ register: true, login: true }}
{storage}
entities:
  user:
    type: auth
    auth: {{ identifier: email, via: password }}
    fields:
      id: {{ type: id }}
      email: {{ type: string, required: true, unique: true }}
  note:
    fields:
      id: {{ type: id }}
      title: {{ type: string, required: true }}
      createdAt: {{ type: datetime }}
repositories:
  users: {{ entity: user }}
  notes:
    entity: note
    softDelete: deletedAt
    ttl: {{ field: createdAt, seconds: 3600 }}
    operations:
{operations}
services:
  users: {{ repository: users }}
  notes: {{ repository: notes }}
  everything: {{ repository: notes, operation: everything }}
{services}
controllers:
  notes:
    base_path: /notes
    routes:
      create:  {{ service: notes, method: POST, path: "", access: public }}
      list:    {{ service: notes, method: GET, path: "", access: public }}
      get:     {{ service: notes, method: GET, path: "/{{id}}", access: public }}
      update:  {{ service: notes, method: PATCH, path: "/{{id}}", access: public }}
      replace: {{ service: notes, method: PUT, path: "/{{id}}", access: public }}
      delete:  {{ service: notes, method: DELETE, path: "/{{id}}", access: public }}
  guarded:
    base_path: /guarded
    routes:
      delete: {{ service: notes, method: DELETE, path: "/{{id}}", access: "*" }}
  archive:
    base_path: /archive
    routes:
      everything: {{ service: everything, method: GET, path: "", access: public }}
{controllers}
"""

SQL_SPEC = _SPEC.format(
    storage='datastores:\n  store: { type: postgres, dsn: "${SQL_DSN}", default: true }',
    operations='      everything: { includeDeleted: true, query: { sql: "SELECT * FROM notes" } }',
    services="",
    controllers="",
)

MONGO_SPEC = _SPEC.format(
    storage="mongo:\n  uri: ${MONGO_URI:-mongodb://localhost:27017}\n  database: ${MONGO_DB:-notes}",
    operations=(
        "      everything: { includeDeleted: true, query: { command: find, filter: {} } }\n"
        "      current: { query: { command: find, filter: {} } }\n"
        '      wipe: { query: { command: deleteOne, filter: { title: "$title" } } }\n'
        '      sweep: { query: { command: deleteMany, filter: { title: "$title" } } }'
    ),
    services=(
        "  wipe: { repository: notes, operation: wipe }\n"
        "  sweep: { repository: notes, operation: sweep }"
    ),
    controllers=(
        "  purge:\n"
        "    base_path: /purge\n"
        "    routes:\n"
        '      wipe: { service: wipe, method: DELETE, path: "/one/{title}", access: public }\n'
        '      sweep: { service: sweep, method: DELETE, path: "/all/{title}", access: public }'
    ),
)

EXPIRED = "2000-01-01T00:00"
"""A creation time long past, as a datetime-local input submits it."""

_STORED = {"kept": False, "removed": True, "guarded": False}


class NotesTable(ABC):
    """The stored notes, read past the API."""

    @abstractmethod
    def rows(self) -> dict[str, bool]:
        """The title of every stored note and whether it carries its removal timestamp."""


@dataclass(frozen=True)
class SqliteNotes(NotesTable):
    path: str

    def rows(self):
        with sqlite3.connect(self.path) as connection:
            return {title: removed is not None for title, removed in connection.execute('SELECT title, "deletedAt" FROM notes')}


@dataclass(frozen=True)
class PostgresNotes(NotesTable):
    dsn: str

    def rows(self):
        with psycopg.connect(self.dsn) as connection:
            return {title: removed is not None for title, removed in connection.execute('SELECT title, "deletedAt" FROM notes')}


@dataclass(frozen=True)
class MongoNotes(NotesTable):
    uri: str
    database: str

    def rows(self):
        with MongoClient(self.uri) as client:
            return {row["title"]: row.get("deletedAt") is not None for row in client[self.database]["notes"].find()}


def _create(client: httpx.Client, title: str, created_at: str) -> str:
    response = client.post("/api/notes", json={"title": title, "createdAt": created_at})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _recently() -> str:
    return (datetime.now(UTC) - timedelta(minutes=1)).isoformat()


def exercise(client: httpx.Client, notes: NotesTable) -> None:
    """Removed and expired notes vanish from every CRUD operation, and only a permitted delete removes a note."""
    ids = {title: _create(client, title, _recently()) for title in ("kept", "removed", "guarded")}
    ids["expired"] = _create(client, "expired", EXPIRED)
    removed, expired, kept = ids["removed"], ids["expired"], ids["kept"]

    assert client.delete(f"/api/guarded/{ids['guarded']}").status_code == 401
    assert client.delete(f"/api/notes/{removed}").status_code == 200
    assert notes.rows().items() >= _STORED.items()

    hiding = (
        client.get, client.delete,
        partial(client.patch, json={"title": "back"}),
        partial(client.put, json={"title": "back"}),
    )
    assert all(request(f"/api/notes/{note}").status_code == 404 for request in hiding for note in (removed, expired))

    stamped = datetime.now(UTC).isoformat()
    writes = (
        partial(client.post, "/api/notes", json={"title": "sneaky", "deletedAt": stamped}),
        partial(client.patch, f"/api/notes/{kept}", json={"deletedAt": stamped}),
        partial(client.patch, f"/api/notes/{kept}", json={"deletedAt": None}),
        partial(client.patch, f"/api/notes/{removed}", json={"deletedAt": None}),
        partial(client.put, f"/api/notes/{kept}", json={"title": "kept", "deletedAt": stamped}),
    )
    assert all(400 <= write().status_code < 500 for write in writes)
    assert notes.rows().items() >= _STORED.items()
    assert sorted(note["title"] for note in client.get("/api/notes").json()) == ["guarded", "kept"]


def exercise_archive(client: httpx.Client, notes: NotesTable) -> None:
    """The includeDeleted operation behind /archive still returns removed notes."""
    exercise(client, notes)
    assert {"kept", "removed"} <= {note["title"] for note in client.get("/api/archive").json()}


def exercise_declared_deletes(client: httpx.Client, notes: NotesTable) -> None:
    """Declared deleteOne and deleteMany operations stamp the removal timestamp in place of erasing."""
    exercise_archive(client, notes)
    for title in ("wiped", "swept"):
        _create(client, title, _recently())
    assert client.delete("/api/purge/one/wiped").status_code == 200
    assert client.delete("/api/purge/all/swept").status_code == 200
    rows = notes.rows()
    assert rows["wiped"] and rows["swept"], rows


Scenario = Callable[[httpx.Client, NotesTable], None]


def verify(
    serve: Callable[[], AbstractContextManager[httpx.Client]], notes: NotesTable, scenario: Scenario = exercise_archive
) -> None:
    """Runs `scenario` on one server, then checks that the next one erases the expired note and nothing else."""
    with serve() as client:
        scenario(client, notes)
    survivors = {title: removed for title, removed in notes.rows().items() if title != "expired"}
    with serve():
        assert wait_until(lambda: notes.rows() == survivors, timeout=15), notes.rows()
