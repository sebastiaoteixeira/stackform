import os
import sys
from pathlib import Path

from fastapi import FastAPI

from .asgi_runner import ASGIApp
from .fastapi_factory import register_fastapi_routes
from ..parsing.parser import load_and_generate_ir
from .repositories import MongoRepository, MongoRepositoryConfig
from .runtime_context_builder import build_runtime_context


def _ensure_spec_dir_importable(yaml_file: str) -> None:
    spec_dir = str(Path(yaml_file).resolve().parent)
    if spec_dir not in sys.path:
        sys.path.insert(0, spec_dir)


def _make_repository(yaml_file: str, schema_file: str | Path | None = None):
    ir = load_and_generate_ir(yaml_file, schema_file).ir
    uri = os.environ.get("YAML_API_MONGO_URI", ir.mongo.uri)
    database = os.environ.get("YAML_API_MONGO_DB", ir.mongo.database)
    repo = MongoRepository(MongoRepositoryConfig(uri=uri, database=database))
    repo.connect()
    return ir, repo


def build_app(yaml_file: str, schema_file: str | Path | None = None) -> FastAPI:
    _ensure_spec_dir_importable(yaml_file)
    ir, repository = _make_repository(yaml_file, schema_file)
    ctx = build_runtime_context(ir)

    app = FastAPI()

    if ir.api.cors:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=ir.api.cors.origins,
            allow_methods=ir.api.cors.methods,
            allow_headers=ir.api.cors.headers,
            allow_credentials=ir.api.cors.credentials,
        )

    register_fastapi_routes(app, ctx, repository)

    return app


def build_raw_app(yaml_file: str, schema_file: str | Path | None = None) -> ASGIApp:
    _ensure_spec_dir_importable(yaml_file)
    ir, repository = _make_repository(yaml_file, schema_file)
    ctx = build_runtime_context(ir)

    return ASGIApp(ctx, repository)
