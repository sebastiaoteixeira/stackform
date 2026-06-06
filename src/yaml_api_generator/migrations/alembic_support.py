"""Drive Alembic migrations for relational datastores declared in a spec.

The combined MetaData is built from the spec's relational collections (reusing
table_from_collection), so create_all and migrations share one source of truth.
A spec graduates to managed migrations by running `migrate new`, which scaffolds
the Alembic environment on first use.
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from yaml_api_generator.ir import IRDocument, IRPostgres
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from yaml_api_generator.server.common.repositories.sql_schema import table_from_collection


def build_metadata(ir: IRDocument, datastore: str) -> sa.MetaData:
    metadata = sa.MetaData()
    for collection in ir.collections.values():
        if (collection.datastore or ir.default_datastore) == datastore:
            table_from_collection(collection, metadata)
    return metadata


def resolve_relational(ir: IRDocument, datastore: str | None) -> tuple[str, str]:
    """Return (name, dsn) of the relational datastore to migrate."""
    relational = {
        name: ds for name, ds in ir.datastores.items() if isinstance(ds, IRPostgres)
    }
    if not relational:
        raise ValueError("No relational datastore declared in this spec")
    if datastore is not None:
        if datastore not in relational:
            raise ValueError(f"'{datastore}' is not a relational datastore")
        return datastore, relational[datastore].dsn
    if len(relational) > 1:
        raise ValueError(
            "Multiple relational datastores; pass --datastore to choose one"
        )
    name, ds = next(iter(relational.items()))
    return name, ds.dsn


def sync_url(dsn: str) -> str:
    return dsn.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


def migrations_dir(spec_path: str) -> Path:
    return Path(spec_path).resolve().parent / "migrations"


def metadata_from_config(config: Config) -> sa.MetaData:
    """Called from the generated env.py to rebuild metadata from the spec."""
    spec_path = config.attributes["spec_path"]
    datastore = config.attributes["datastore"]
    ir = load_and_generate_ir(spec_path).ir
    return build_metadata(ir, datastore)


def make_config(spec_path: str, datastore: str | None = None) -> Config:
    ir = load_and_generate_ir(spec_path).ir
    name, dsn = resolve_relational(ir, datastore)
    directory = migrations_dir(spec_path)
    ensure_scaffold(directory)

    config = Config()
    config.set_main_option("script_location", str(directory))
    config.set_main_option("sqlalchemy.url", sync_url(dsn))
    config.attributes["spec_path"] = str(spec_path)
    config.attributes["datastore"] = name
    config.attributes["metadata"] = build_metadata(ir, name)
    return config


def ensure_scaffold(directory: Path) -> None:
    versions = directory / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    env_py = directory / "env.py"
    if not env_py.exists():
        env_py.write_text(_ENV_PY)
    mako = directory / "script.py.mako"
    if not mako.exists():
        mako.write_text(_SCRIPT_MAKO)


def new_revision(config: Config, message: str) -> None:
    directory = Path(config.get_main_option("script_location")) / "versions"
    first = not any(directory.glob("*.py"))
    command.revision(config, message=message, autogenerate=True)
    if first and _schema_already_present(config):
        command.stamp(config, "head")


def upgrade(config: Config, target: str = "head") -> None:
    command.upgrade(config, target)


def downgrade(config: Config, target: str = "-1") -> None:
    command.downgrade(config, target)


def status(config: Config) -> None:
    command.current(config, verbose=True)


def history(config: Config) -> None:
    command.history(config, verbose=True)


def _schema_already_present(config: Config) -> bool:
    metadata: sa.MetaData = config.attributes["metadata"]
    engine = sa.create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        existing = set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
    return bool(metadata.tables) and set(metadata.tables) <= existing


_ENV_PY = '''"""Alembic environment, wired to the spec's metadata."""

from sqlalchemy import create_engine, pool

from alembic import context
from yaml_api_generator.migrations.alembic_support import metadata_from_config

config = context.config
target_metadata = metadata_from_config(config)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''


_SCRIPT_MAKO = '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
'''
