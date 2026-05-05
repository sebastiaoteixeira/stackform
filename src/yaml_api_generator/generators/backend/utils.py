"""Shared utilities for backend generators."""
from .compile_context import CompileContext, IdentityCollectionDescriptor


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
