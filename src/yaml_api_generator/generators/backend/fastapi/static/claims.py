from typing import Any


def resolve_claim_path(claims: dict[str, Any], path: str) -> Any | None:
    if not path or not path.strip():
        return None
    if path in claims:
        return claims[path]

    current: Any = claims
    for segment in path.split("."):
        if segment == "*":
            if not isinstance(current, dict) or len(current) != 1:
                return None
            current = next(iter(current.values()))
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(segment)
            if current is None:
                return None

    return current


async def resolve_relations(
    claims: dict[str, Any],
    relations: list[dict[str, Any]],
    lookup: Any,
) -> dict[str, Any | None]:
    result: dict[str, Any | None] = {}
    for rel in relations:
        fk_field: str = rel["fk_field"]
        collection: str = rel["collection"]
        id_field: str = rel["id_field"]
        match: dict[str, str] = rel["match"]

        query: dict[str, Any] = {}
        skip = False
        for target_local_field, claim_path in match.items():
            resolved = resolve_claim_path(claims, claim_path)
            if resolved is None:
                skip = True
                break
            query[target_local_field] = resolved

        if skip:
            result[fk_field] = None
            continue

        record = await lookup(collection, query)
        result[fk_field] = record[id_field] if record is not None else None

    return result
