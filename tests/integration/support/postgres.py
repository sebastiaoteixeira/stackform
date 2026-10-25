"""A real PostgreSQL: YAML_API_TEST_POSTGRES_URI when set, otherwise a throwaway container."""

from urllib.parse import urlsplit
from uuid import uuid4

import psycopg

from .docker import Service

PASSWORD = "postgres"


def _connectable(uri: str) -> bool:
    try:
        with psycopg.connect(uri, connect_timeout=1):
            return True
    except psycopg.Error:
        return False


def fresh_database(uri: str) -> str:
    """The asyncpg DSN of a new empty database on the server at `uri`."""
    name = f"payloads_{uuid4().hex}"
    with psycopg.connect(uri, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')
    return urlsplit(uri)._replace(scheme="postgresql+asyncpg", path=f"/{name}").geturl()


POSTGRES = Service(
    name="postgres",
    image="postgres:16-alpine",
    port=5432,
    scheme="postgresql",
    override="YAML_API_TEST_POSTGRES_URI",
    ready=_connectable,
    env={"POSTGRES_PASSWORD": PASSWORD},
    userinfo=f"postgres:{PASSWORD}@",
)
