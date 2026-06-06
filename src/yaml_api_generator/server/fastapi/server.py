"""FastAPI server builder."""

from pathlib import Path

from fastapi import FastAPI

from ..common.context_builder import build_runtime_context
from ..common.loader import create_repositories, ensure_spec_dir_importable
from .factory import register_fastapi_routes


def build_app(yaml_file: str, schema_file: str | Path | None = None) -> FastAPI:
    """Build FastAPI application from YAML specification.

    Args:
        yaml_file: Path to YAML API specification
        schema_file: Optional path to JSON schema for validation

    Returns:
        Configured FastAPI application with routes and middleware
    """
    ensure_spec_dir_importable(yaml_file)
    ir, registry = create_repositories(yaml_file, schema_file)
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

    register_fastapi_routes(app, ctx, registry)

    return app
