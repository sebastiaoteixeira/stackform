"""Raw ASGI server builder."""

from pathlib import Path

from yaml_api_generator.parsers.transformers.file_validation import reject_file_fields
from yaml_api_generator.parsers.transformers.provider_validation import reject_external_login

from ..common.context_builder import build_runtime_context
from ..common.loader import create_repositories, ensure_spec_dir_importable
from ..common.vendored_packages import install_vendored_packages
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
    reject_file_fields(
        {collection.entity_name: collection.fields for collection in ir.collections.values()},
        "raw",
    )
    reject_external_login(ir.providers, "raw")
    install_vendored_packages(ir.vendored_imports)
    ctx = build_runtime_context(ir)

    return ASGIApp(ctx, registry, ir)
