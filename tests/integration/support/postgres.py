"""A real PostgreSQL: YAML_API_TEST_POSTGRES_URI when set, otherwise a throwaway container."""

from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg

from .docker import Service


def _connectable(uri: str) -> bool:
    try:
        psycopg.connect(uri, connect_timeout=1).close()
        return True
    except psycopg.Error:
        return False


POSTGRES = Service(
    name="postgres",
    image="postgres:16",
    port=5432,
    scheme="postgresql",
    override="YAML_API_TEST_POSTGRES_URI",
    ready=_connectable,
    env={"POSTGRES_PASSWORD": "postgres"},
    userinfo="postgres:postgres@",
)


@contextmanager
def fresh_database(uri: str) -> Iterator[str]:
    """A new empty database on the server at `uri`, as an asyncpg SQLAlchemy URL, dropped afterwards."""
    name = f"test_{uuid4().hex}"
    with psycopg.connect(uri, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        try:
            yield urlsplit(uri)._replace(scheme="postgresql+asyncpg", path=f"/{name}").geturl()
        finally:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
