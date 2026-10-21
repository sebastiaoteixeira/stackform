"""Raw ASGI server builder."""

from pathlib import Path

from starlette import types

from yaml_api_generator.parsers.transformers.file_validation import reject_file_fields

from ..common.context_builder import build_runtime_context
from ..common.http_middleware import api_middleware, wrap_asgi
from ..common.loader import create_repositories, ensure_spec_dir_importable
from ..common.vendored_packages import install_vendored_packages
from .runner import ASGIApp


def build_raw_app(yaml_file: str, schema_file: str | Path | None = None) -> types.ASGIApp:
    """Build raw ASGI application from YAML specification.

    Args:
        yaml_file: Path to YAML API specification
        schema_file: Optional path to JSON schema for validation

    Returns:
        ASGI application wrapped in the middleware the spec enables
    """
    ensure_spec_dir_importable(yaml_file)
    ir, registry = create_repositories(yaml_file, schema_file)
    reject_file_fields(
        {collection.entity_name: collection.fields for collection in ir.collections.values()},
        "raw",
    )
    install_vendored_packages(ir.vendored_imports)
    ctx = build_runtime_context(ir)

    return wrap_asgi(ASGIApp(ctx, registry, ir), api_middleware(ir.api))
