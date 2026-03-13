import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .asgi_runner import ASGIApp
from .fastapi_factory import register_fastapi_routes
from .parser import load_and_generate_ir
from .repositories import MongoRepository, MongoRepositoryConfig


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


def build_app(yaml_file: str, schema_file: str | Path) -> FastAPI:
    ir = load_and_generate_ir(yaml_file, schema_file)

    app = FastAPI(lifespan=lifespan)

    repository = MongoRepository(
        MongoRepositoryConfig(
            uri=os.environ.get("YAML_API_MONGO_URI", "mongodb://localhost:27017"),
            database=os.environ.get("YAML_API_MONGO_DB", "yaml_api"),
        )
    )
    repository.connect()

    register_fastapi_routes(app, ir, repository)

    return app


def build_raw_app(yaml_file: str, schema_file: str | Path) -> ASGIApp:
    ir = load_and_generate_ir(yaml_file, schema_file)

    repository = MongoRepository(
        MongoRepositoryConfig(
            uri=os.environ.get("YAML_API_MONGO_URI", "mongodb://localhost:27017"),
            database=os.environ.get("YAML_API_MONGO_DB", "yaml_api"),
        )
    )
    repository.connect()

    return ASGIApp(ir, repository)


