"""Shared utilities for backend generators."""

from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment

from yaml_api_generator.ir.api import IRPagination

from .builders.settings_builder import build_settings_fields, generated_secret_values
from .compile_context import CompileContext, IdentityCollectionDescriptor


_RUNTIME_MODULES = frozenset(
    {
        "dpop", "pagination", "fields", "payloads", "files", "multipart", "file_requests", "filesystem_store",
        "s3_store", "sql_types", "operations", "ids", "mongo_operations", "sql_operations", "handler_requests",
        "lifecycle", "mongo_lifecycle", "sql_lifecycle",
    }
)


def runtime_module_source(name: str) -> str:
    if name not in _RUNTIME_MODULES:
        raise ValueError(f"Unknown runtime module: {name}")
    return files("yaml_api_generator.runtime").joinpath(f"{name}.py").read_text()


def write_runtime_modules(directory: Path, names: Iterable[str]) -> None:
    for name in names:
        (directory / f"{name}.py").write_text(runtime_module_source(name))


MONGO_RUNTIME_MODULES = (
    "pagination", "operations", "ids", "mongo_operations", "handler_requests", "lifecycle", "mongo_lifecycle",
)
SQL_RUNTIME_MODULES = ("sql_types", "sql_operations", "lifecycle", "sql_lifecycle")


def write_environment_files(
    env: Environment, context: CompileContext, output_dir: Path
) -> None:
    fields = build_settings_fields(context)
    generated = generated_secret_values(fields)
    values = {
        field.env_name: generated.get(field.env_name, field.default or "")
        for field in fields
    }
    examples = {
        field.env_name: (
            f"<{field.env_name.lower()}>" if field.secret else field.default or ""
        )
        for field in fields
    }
    template = env.get_template("env.jinja")
    (output_dir / ".env").write_text(
        template.render(settings_fields=fields, values=values)
    )
    (output_dir / ".env.example").write_text(
        template.render(settings_fields=fields, values=examples)
    )


def pagination_config(pagination: IRPagination) -> dict:
    return {
        "strategy": pagination.strategy,
        "size": {
            "default": pagination.size.default,
            "max": pagination.size.max,
        },
        "count": pagination.count,
        "on_overflow": pagination.on_overflow,
        "envelope": pagination.envelope,
        "sort": [
            {"field": key.field, "dir": key.dir}
            for key in pagination.sort
        ],
    }


def find_identity(
    context: CompileContext, col_name: str
) -> IdentityCollectionDescriptor | None:
    """Find identity collection by name."""
    for ic in context.auth.identity_collections:
        if ic.name == col_name:
            return ic
    return None


def group_by_collection(context: CompileContext) -> dict[str, dict]:
    """Group models and routes by collection name."""
    groups: dict[str, dict] = {}
    for col_name in context.collections:
        groups[col_name] = {"models": [], "routes": []}

    for model in context.models:
        groups[model.collection]["models"].append(model)
    for route in context.routes:
        if route.collection is None:
            continue
        groups[route.collection]["routes"].append(route)

    return groups


def extract_identity_fields(context: CompileContext, col_name: str) -> list[str]:
    """Extract unique identity field names from bindings."""
    identity = find_identity(context, col_name)
    if identity is None:
        return []

    identity_fields: list[str] = []
    seen: set[str] = set()
    for binding in identity.bindings:
        if binding.identifier not in seen:
            identity_fields.append(binding.identifier)
            seen.add(binding.identifier)

    return identity_fields
