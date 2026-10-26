"""Entity keys resolved along the ``extends`` chain, as the entity desugarer later merges them."""

from typing import Any


def inherited(entity: str, entities: dict[str, Any], key: str) -> Any:
    """Walk the ``extends`` chain returning the nearest ``key`` value."""
    seen: set[str] = set()
    current: str | None = entity
    while isinstance(current, str) and current not in seen:
        seen.add(current)
        node = entities.get(current)
        if not isinstance(node, dict):
            return None
        if key in node:
            return node[key]
        current = node.get("extends")
    return None


def inherited_fields(entity: str, entities: dict[str, Any]) -> dict[str, Any]:
    """Merge ``fields`` along the ``extends`` chain (parents first)."""
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: str | None = entity
    while isinstance(current, str) and current not in seen:
        seen.add(current)
        node = entities.get(current)
        if not isinstance(node, dict):
            break
        fields = node.get("fields")
        if isinstance(fields, dict):
            chain.append(fields)
        current = node.get("extends")
    merged: dict[str, Any] = {}
    for fields in reversed(chain):
        merged.update(fields)
    return merged
