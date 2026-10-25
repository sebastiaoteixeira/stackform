"""Soft deletion and expiry over HTTP on PostgreSQL, served by the dev server and by a generated FastAPI app."""

import pytest

from tests.integration.support.postgres import fresh_database
from tests.integration.support.spec_apps import SQL_BACKENDS, serve
from tests.support.lifecycle import VERSIONS, PostgresNotes, sql_spec, verify

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("backend", SQL_BACKENDS, ids=lambda backend: backend.name)
def test_removed_and_expired_notes(tmp_path, postgres_uri, backend, version):
    spec = tmp_path / "notes.yaml"
    spec.write_text(sql_spec(version=version))
    with fresh_database(postgres_uri) as dsn:
        notes = PostgresNotes(dsn.replace("postgresql+asyncpg", "postgresql", 1))
        verify(lambda: serve(backend, spec, {"SQL_DSN": dsn}), notes)
