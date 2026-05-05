"""Common utilities for loading YAML specs and initializing repositories."""

import os
import sys
from pathlib import Path

from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from .repositories import MongoRepository, MongoRepositoryConfig


def ensure_spec_dir_importable(yaml_file: str) -> None:
    """Add YAML spec directory to Python path for custom imports."""
    spec_dir = str(Path(yaml_file).resolve().parent)
    if spec_dir not in sys.path:
        sys.path.insert(0, spec_dir)


def create_repository(yaml_file: str, schema_file: str | Path | None = None):
    """Load IR and create MongoDB repository.

    Returns:
        Tuple of (IRDocument, MongoRepository)
    """
    ir = load_and_generate_ir(yaml_file, schema_file).ir
    uri = os.environ.get("YAML_API_MONGO_URI", ir.mongo.uri)
    database = os.environ.get("YAML_API_MONGO_DB", ir.mongo.database)
    repo = MongoRepository(MongoRepositoryConfig(uri=uri, database=database))
    repo.connect()
    return ir, repo
