import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .asgi_runner import ASGIApp
from .fastapi_factory import register_fastapi_routes
from ..parsing.parser import load_and_generate_ir
from .repositories import MongoRepository, MongoRepositoryConfig
from .runtime_context_builder import build_runtime_context


@asynccontextmanager
async def lifespan(app: FastAPI):
    repository = MongoRepository(
        MongoRepositoryConfig(
            uri=os.environ.get("YAML_API_MONGO_URI", "mongodb://localhost:27017"),
            database=os.environ.get("YAML_API_MONGO_DB", "yaml_api"),
        )
    )
    repository.connect()
    app.state.repository = repository
    yield
    repository.close()


def _ensure_spec_dir_importable(yaml_file: str) -> None:
    spec_dir = str(Path(yaml_file).resolve().parent)
    if spec_dir not in sys.path:
        sys.path.insert(0, spec_dir)


def build_app(yaml_file: str, schema_file: str | Path | None = None) -> FastAPI:
    _ensure_spec_dir_importable(yaml_file)
    ir = load_and_generate_ir(yaml_file, schema_file)
    ctx = build_runtime_context(ir)

    app = FastAPI(lifespan=lifespan)

    repository = MongoRepository(
        MongoRepositoryConfig(
            uri=os.environ.get("YAML_API_MONGO_URI", "mongodb://localhost:27017"),
            database=os.environ.get("YAML_API_MONGO_DB", "yaml_api"),
        )
    )
    repository.connect()

    register_fastapi_routes(app, ctx, repository)

    return app


def build_raw_app(yaml_file: str, schema_file: str | Path | None = None) -> ASGIApp:
    _ensure_spec_dir_importable(yaml_file)
    ir = load_and_generate_ir(yaml_file, schema_file)
    ctx = build_runtime_context(ir)

    repository = MongoRepository(
        MongoRepositoryConfig(
            uri=os.environ.get("YAML_API_MONGO_URI", "mongodb://localhost:27017"),
            database=os.environ.get("YAML_API_MONGO_DB", "yaml_api"),
        )
    )
    repository.connect()

    return ASGIApp(ctx, repository)
