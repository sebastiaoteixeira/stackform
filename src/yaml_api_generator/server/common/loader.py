"""Common utilities for loading YAML specs and initializing repositories."""

import os
import sys
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


def create_repositories(yaml_file: str, schema_file: str | Path | None = None):
    """Load IR and build a connected repository registry.

    Returns:
        Tuple of (IRDocument, RepositoryRegistry)
    """
    ir = load_and_generate_ir(yaml_file, schema_file).ir
    manage_schema = not (Path(yaml_file).resolve().parent / "migrations").exists()
    registry = build_registry(ir, create_schema=manage_schema)
    return ir, registry


def build_registry(ir: IRDocument, create_schema: bool = True) -> RepositoryRegistry:
    repositories: dict[str, BaseRepository] = {}
    for name, datastore in ir.datastores.items():
        repo = _build_repository(name, datastore, ir, create_schema)
        repo.connect()
        repositories[name] = repo

    bindings = {
        col_name: (col.datastore or ir.default_datastore)
        for col_name, col in ir.collections.items()
    }
    return RepositoryRegistry(repositories, bindings, ir.default_datastore)


def _build_repository(
    name: str, datastore, ir: IRDocument, create_schema: bool = True
) -> BaseRepository:
    if isinstance(datastore, IRMongo):
        is_default = name == ir.default_datastore
        uri = os.environ.get("YAML_API_MONGO_URI", datastore.uri) if is_default else datastore.uri
        database = (
            os.environ.get("YAML_API_MONGO_DB", datastore.database)
            if is_default
            else datastore.database
        )
        return MongoRepository(MongoRepositoryConfig(uri=uri, database=database))

    if isinstance(datastore, IRPostgres):
        from .repositories.sql import SQLRepository

        collections = [
            col for col in ir.collections.values()
            if (col.datastore or ir.default_datastore) == name
        ]
        dsn = os.environ.get(f"YAML_API_DB_{name.upper()}_DSN", datastore.dsn)
        return SQLRepository(dsn=dsn, collections=collections, create_schema=create_schema)

    raise ValueError(f"Unsupported datastore type for '{name}': {type(datastore).__name__}")
