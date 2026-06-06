"""Raw ASGI server builder."""

from pathlib import Path

from ..common.context_builder import build_runtime_context
from ..common.loader import create_repositories, ensure_spec_dir_importable
from .runner import ASGIApp


def build_raw_app(yaml_file: str, schema_file: str | Path | None = None) -> ASGIApp:
    """Build raw ASGI application from YAML specification.

    Args:
        yaml_file: Path to YAML API specification
        schema_file: Optional path to JSON schema for validation

    Returns:
        Configured ASGI application
    """
    ensure_spec_dir_importable(yaml_file)
    ir, registry = create_repositories(yaml_file, schema_file)
    ctx = build_runtime_context(ir)

    return ASGIApp(ctx, registry)
