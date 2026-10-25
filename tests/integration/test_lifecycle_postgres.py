"""Soft deletion and expiry over HTTP on PostgreSQL, served by the dev server and by a generated FastAPI app."""

import pytest

from tests.integration.support.postgres import fresh_database
from tests.integration.support.spec_apps import SQL_BACKENDS, serve
from tests.support.lifecycle import SQL_SPEC, PostgresNotes, verify

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("backend", SQL_BACKENDS, ids=lambda backend: backend.name)
def test_removed_and_expired_notes(tmp_path, postgres_uri, backend):
    spec = tmp_path / "notes.yaml"
    spec.write_text(SQL_SPEC)
    with fresh_database(postgres_uri) as dsn:
        notes = PostgresNotes(dsn.replace("postgresql+asyncpg", "postgresql", 1))
        verify(lambda: serve(backend, spec, {"SQL_DSN": dsn}), notes)
