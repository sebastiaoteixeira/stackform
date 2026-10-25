"""A soft-deleting, expiring notes API and the HTTP behaviour every backend serving it must show."""

import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from pymongo import MongoClient

from tests.integration.support.network import wait_until

_SPEC = """
version: "0.2"
api: {{ basePath: /api }}
{storage}
entities:
  note:
    fields:
      id: {{ type: id }}
      title: {{ type: string, required: true }}
      createdAt: {{ type: datetime }}
repositories:
  notes:
    entity: note
    softDelete: deletedAt
    ttl: {{ field: createdAt, seconds: 3600 }}
    operations:
{operations}
services:
  notes: {{ repository: notes }}
  everything: {{ repository: notes, operation: everything }}
controllers:
  notes:
    base_path: /notes
    routes:
      create: {{ service: notes, method: POST, path: "", access: public }}
      list:   {{ service: notes, method: GET, path: "", access: public }}
      get:    {{ service: notes, method: GET, path: "/{{id}}", access: public }}
      update: {{ service: notes, method: PATCH, path: "/{{id}}", access: public }}
      delete: {{ service: notes, method: DELETE, path: "/{{id}}", access: public }}
  archive:
    base_path: /archive
    routes:
      everything: {{ service: everything, method: GET, path: "", access: public }}
"""

SQL_SPEC = _SPEC.format(
    storage='datastores:\n  store: { type: postgres, dsn: "postgresql+asyncpg://localhost/notes", default: true }',
    operations='      everything: { includeDeleted: true, query: { sql: "SELECT * FROM notes" } }',
)

MONGO_SPEC = _SPEC.format(
    storage="mongo:\n  uri: ${MONGO_URI:-mongodb://localhost:27017}\n  database: ${MONGO_DB:-notes}",
    operations=(
        "      everything: { includeDeleted: true, query: { command: find, filter: {} } }\n"
        "      current: { query: { command: find, filter: {} } }"
    ),
)

LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


class NotesTable(ABC):
    """The stored notes, read and written past the API."""

    @abstractmethod
    def rows(self) -> dict[str, bool]:
        """The title of every stored note and whether it carries its removal timestamp."""

    @abstractmethod
    def stamp(self, title: str, instant: datetime) -> None:
        """Sets the creation timestamp the time to live counts from."""


@dataclass(frozen=True)
class SqliteNotes(NotesTable):
    path: str

    def rows(self):
        with sqlite3.connect(self.path) as connection:
            return {title: removed is not None for title, removed in connection.execute('SELECT title, "deletedAt" FROM notes')}

    def stamp(self, title, instant):
        with sqlite3.connect(self.path) as connection:
            connection.execute('UPDATE notes SET "createdAt" = ? WHERE title = ?', (instant.strftime("%Y-%m-%d %H:%M:%S.%f"), title))


@dataclass(frozen=True)
class MongoNotes(NotesTable):
    uri: str
    database: str

    def rows(self):
        with MongoClient(self.uri) as client:
            return {row["title"]: row.get("deletedAt") is not None for row in client[self.database]["notes"].find()}

    def stamp(self, title, instant):
        with MongoClient(self.uri) as client:
            client[self.database]["notes"].update_one({"title": title}, {"$set": {"createdAt": instant.isoformat()}})


def _create(client: httpx.Client, title: str) -> str:
    response = client.post("/api/notes", json={"title": title})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def exercise(client: httpx.Client, notes: NotesTable) -> None:
    """Removed and expired notes vanish from every generated CRUD operation."""
    ids = {title: _create(client, title) for title in ("kept", "removed", "expired")}
    notes.stamp("kept", datetime.now(UTC) - timedelta(minutes=1))
    notes.stamp("expired", LONG_AGO)
    removed, expired = ids["removed"], ids["expired"]

    assert client.delete(f"/api/notes/{removed}").status_code == 200
    assert client.delete(f"/api/notes/{removed}").status_code == 404
    assert client.get(f"/api/notes/{removed}").status_code == 404
    assert client.patch(f"/api/notes/{removed}", json={"title": "back"}).status_code == 404
    assert client.get(f"/api/notes/{expired}").status_code == 404
    assert client.patch(f"/api/notes/{expired}", json={"title": "back"}).status_code == 404
    assert client.get(f"/api/notes/{ids['kept']}").status_code == 200
    assert [note["title"] for note in client.get("/api/notes").json()] == ["kept"]


def exercise_archive(client: httpx.Client, notes: NotesTable) -> None:
    """The includeDeleted operation behind /archive still returns removed notes."""
    exercise(client, notes)
    assert {"kept", "removed"} <= {note["title"] for note in client.get("/api/archive").json()}


Scenario = Callable[[httpx.Client, NotesTable], None]


def verify(
    serve: Callable[[], AbstractContextManager[httpx.Client]], notes: NotesTable, scenario: Scenario = exercise
) -> None:
    """Runs `scenario` on one server, then checks that the next one erases the expired note as it starts."""
    with serve() as client:
        scenario(client, notes)
    with serve():
        assert wait_until(lambda: notes.rows() == {"kept": False, "removed": True}, timeout=15), notes.rows()
