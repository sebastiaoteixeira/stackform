import os
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


def build_app(yaml_file: str, schema_file: str | Path | None = None) -> FastAPI:
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
