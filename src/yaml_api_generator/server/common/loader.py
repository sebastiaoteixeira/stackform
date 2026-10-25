"""Common utilities for loading YAML specs and initializing repositories."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from yaml_api_generator.ir import IRDocument, IRMongo, IRPostgres
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from .repositories import (
    BaseRepository,
    MongoRepository,
    MongoRepositoryConfig,
    RepositoryRegistry,
)


def ensure_spec_dir_importable(yaml_file: str) -> None:
    """Add YAML spec directory to Python path for custom imports."""
    spec_dir = str(Path(yaml_file).resolve().parent)
    if spec_dir not in sys.path:
        sys.path.insert(0, spec_dir)


@dataclass(frozen=True)
class SchemaManagement:
    """Which datastore families evolve their schema through versioned migrations.

    Each family graduates from create-on-connect on its own migrations tree, so
    adopting Alembic never silences MongoDB index creation and vice versa.
    """

    sql: bool = False
    mongo: bool = False

    @classmethod
    def for_spec(cls, yaml_file: str | Path) -> "SchemaManagement":
        spec_dir = Path(yaml_file).resolve().parent
        return cls(
            sql=(spec_dir / "migrations").is_dir(),
            mongo=(spec_dir / "mongo_migrations").is_dir(),
        )


def create_repositories(yaml_file: str, schema_file: str | Path | None = None):
    """Load IR and build a connected repository registry.

    Returns:
        Tuple of (IRDocument, RepositoryRegistry)
    """
    ir = load_and_generate_ir(yaml_file, schema_file).ir
    return ir, build_registry(ir, SchemaManagement.for_spec(yaml_file))


def mongo_connection_params(ir: IRDocument, name: str) -> tuple[str, str]:
    datastore = ir.datastores[name]
    is_default = name == ir.default_datastore
    uri = os.environ.get("YAML_API_MONGO_URI", datastore.uri) if is_default else datastore.uri
    database = (
        os.environ.get("YAML_API_MONGO_DB", datastore.database)
        if is_default
        else datastore.database
    )
    return uri, database


async def initialize_indexes(ir: IRDocument, registry: RepositoryRegistry) -> None:
    """Materialize unique:true fields as backend-level unique indexes.

    SQL backends already enforce uniqueness through the column constraint built
    into the table schema; only document stores need explicit index creation.
    """
    for col_name, collection in ir.collections.items():
        repo = registry.for_collection(col_name)
        if not isinstance(repo, MongoRepository) or not repo.manage_indexes:
            continue
        for field_name, cfg in collection.fields.items():
            if isinstance(cfg, dict) and cfg.get("unique"):
                await repo.create_unique_index(col_name, field_name)


def build_registry(
    ir: IRDocument, managed: SchemaManagement = SchemaManagement()
) -> RepositoryRegistry:
    repositories: dict[str, BaseRepository] = {}
    for name, datastore in ir.datastores.items():
        repo = _build_repository(name, datastore, ir, managed)
        repo.connect()
        repositories[name] = repo

    bindings = {
        col_name: (col.datastore or ir.default_datastore)
        for col_name, col in ir.collections.items()
    }
    return RepositoryRegistry(repositories, bindings, ir.default_datastore)


def _build_repository(
    name: str, datastore, ir: IRDocument, managed: SchemaManagement
) -> BaseRepository:
    collections = [
        col for col in ir.collections.values()
        if (col.datastore or ir.default_datastore) == name
    ]
    if isinstance(datastore, IRMongo):
        uri, database = mongo_connection_params(ir, name)
        return MongoRepository(
            MongoRepositoryConfig(uri=uri, database=database),
            collections,
            manage_indexes=not managed.mongo,
        )

    if isinstance(datastore, IRPostgres):
        from .repositories.sql import SQLRepository

        dsn = os.environ.get(f"YAML_API_DB_{name.upper()}_DSN", datastore.dsn)
        return SQLRepository(dsn=dsn, collections=collections, create_schema=not managed.sql)

    raise ValueError(f"Unsupported datastore type for '{name}': {type(datastore).__name__}")
