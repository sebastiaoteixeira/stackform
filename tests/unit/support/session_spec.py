"""A register/login spec whose session block and datastore vary per test."""

from pathlib import Path

from tests.unit.support.generated_apps import write_spec

_SPEC = """
version: "{version}"
api:
  basePath: /api
  operations: {{ auth: {{ register: true, login: true }} }}
{store}
entities:
  user:
    type: auth
    auth: {{ identifier: email, via: password }}
    fields:
      id: {{ type: id }}
      email: {{ type: string, required: true, unique: true }}
repositories:
  users: {{ entity: user }}
services:
  users: {{ repository: users }}
controllers:
  users:
    service: users
    base_path: /users
    access: "*"
    operations:
      register: {{ access: public }}
      login: {{ access: public }}
{session}
"""

SQL = 'datastores:\n  store: { type: postgres, dsn: "postgresql+asyncpg://localhost/ttl", default: true }'


def mongo(uri: str = "mongodb://localhost:27017", database: str = "ttl") -> str:
    return f'mongo: {{ uri: "{uri}", database: {database} }}'


LASTING = {"session: { ttl: 120 }": 120, "": 24 * 3600}
ROTATING = {"session: { ttl: 300, refresh: true }": 300, "session: { refresh: true }": 900}


def session_spec(directory: Path, session: str, version: str = "0.2", store: str = SQL) -> Path:
    return write_spec(directory, _SPEC.format(version=version, store=store, session=session))
