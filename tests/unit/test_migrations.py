"""Tests for `stackform migrate` over Alembic.

Uses a Postgres-typed datastore whose DSN points at sync SQLite, so the full
Alembic flow runs without a Postgres server.
"""

import textwrap

import sqlalchemy as sa
import pytest

from yaml_api_generator.migrations.alembic_support import (
    build_metadata,
    make_config,
    new_revision,
    resolve_relational,
    sync_url,
    upgrade,
)
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from yaml_api_generator.server.common.loader import build_registry
from yaml_api_generator.server.common.repositories.sql import SQLRepository


def _write_spec(tmp_path, dsn):
    spec = tmp_path / "spec.yaml"
    spec.write_text(textwrap.dedent(f"""
        version: "0.2"
        api: {{ basePath: /api }}
        datastores:
          store: {{ type: postgres, dsn: "{dsn}", default: true }}
        entities:
          task: {{ fields: {{ id: {{ type: id }}, title: {{ type: string, required: true }} }} }}
        repositories:
          tasks: {{ entity: task }}
        services: {{ tasks: {{ repository: tasks }} }}
        controllers:
          tasks:
            base_path: /tasks
            routes: {{ list: {{ service: tasks, method: GET, path: "", access: public }} }}
    """))
    return spec


def test_sync_url_strips_async_drivers():
    assert sync_url("postgresql+asyncpg://h/db") == "postgresql+psycopg://h/db"
    assert sync_url("sqlite+aiosqlite:///x.db") == "sqlite:///x.db"


def test_resolve_relational_picks_postgres(tmp_path):
    spec = _write_spec(tmp_path, "sqlite:///x.db")
    ir = load_and_generate_ir(str(spec)).ir
    name, dsn = resolve_relational(ir, None)
    assert name == "store"
    assert build_metadata(ir, name).tables


def test_new_then_up_creates_tables(tmp_path):
    db = tmp_path / "db.sqlite"
    spec = _write_spec(tmp_path, f"sqlite:///{db}")
    config = make_config(str(spec))

    new_revision(config, "init")
    revisions = list((tmp_path / "migrations" / "versions").glob("*.py"))
    assert len(revisions) == 1
    assert "create_table" in revisions[0].read_text()

    upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{db}")
    assert "tasks" in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_graduation_stamps_existing_schema(tmp_path):
    db = tmp_path / "db.sqlite"
    spec = _write_spec(tmp_path, f"sqlite:///{db}")
    ir = load_and_generate_ir(str(spec)).ir

    # Simulate prior create_all: tables already exist.
    metadata = build_metadata(ir, "store")
    engine = sa.create_engine(f"sqlite:///{db}")
    metadata.create_all(engine)

    new_revision(make_config(str(spec)), "init")

    stamped = engine.connect().execute(sa.text("SELECT version_num FROM alembic_version")).all()
    engine.dispose()
    assert len(stamped) == 1  # existing DB stamped at baseline, not re-created


def test_loader_disables_create_all_when_migrations_present(tmp_path):
    spec = _write_spec(tmp_path, "sqlite+aiosqlite:///x.db")
    ir = load_and_generate_ir(str(spec)).ir
    (tmp_path / "migrations").mkdir()

    # create_repositories derives create_schema from the migrations dir.
    from yaml_api_generator.server.common.loader import create_repositories
    _, registry = create_repositories(str(spec))
    repo = registry.for_collection("tasks")
    assert isinstance(repo, SQLRepository)
    assert repo._create_schema is False
