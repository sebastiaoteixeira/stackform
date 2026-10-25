"""Map external identity claims to a local record, provisioning it and its relations when allowed."""

from typing import Any

from fastapi import HTTPException

from yaml_api_generator.ir.api import IRProviderBinding, IRProviderRelation
from ..repositories import BaseRepository, RepositoryRegistry
from ..server_context import RuntimeCollectionDescriptor
from ..utils.ids import generate_id
from ..utils.field_access import resolve_claim_path
from .login_codes import login_codes


async def _resolve_relations(
    claims: dict[str, Any],
    relations: dict[str, IRProviderRelation],
    registry: RepositoryRegistry | None,
    collections: dict[str, RuntimeCollectionDescriptor],
) -> dict[str, Any]:
    if not relations or registry is None:
        return {}

    result: dict[str, Any] = {}
    for fk_field, relation in relations.items():
        target = collections.get(relation.collection)
        if target is None:
            result[fk_field] = None
            continue
        resolved = {
            local: resolve_claim_path(claims, claim_path)
            for local, claim_path in relation.match.items()
        }
        if any(v is None for v in resolved.values()):
            result[fk_field] = None
            continue
        target_repo = registry.for_collection(relation.collection)
        documents = await target_repo.list(relation.collection)
        matched = next(
            (d for d in documents if all(str(d.get(k, "")) == str(v) for k, v in resolved.items())),
            None,
        )
        result[fk_field] = matched.get(target.id_field) if matched is not None else None
    return result


async def resolve_record(
    claims: dict[str, Any],
    binding: IRProviderBinding,
    collection: RuntimeCollectionDescriptor,
    repo: BaseRepository,
    is_idp: bool = False,
    collections: dict[str, RuntimeCollectionDescriptor] | None = None,
    registry: RepositoryRegistry | None = None,
) -> dict[str, Any] | None:
    """Map IdP/app claims to a local record, provisioning it when allowed.

    Under trust:idp (is_idp=True), the IdP sub is the primary key: we look up
    by id_field == sub and provision with id_field = sub so that
    principal.sub == record.id_field == token.sub — one key everywhere.
    Under trust:app, we use the mapped identifier field and generate_id as before.
    """
    user_fields = {
        local_field: v
        for local_field, oidc_claim in binding.claim_mapping.items()
        if (v := resolve_claim_path(claims, oidc_claim)) is not None
    }
    if binding.identifier not in user_fields:
        user_fields[binding.identifier] = (
            claims.get("email") or claims.get("login") or claims.get("sub")
        )

    fk_fields = await _resolve_relations(claims, binding.relations, registry, collections or {})
    documents = await repo.list(collection.name)

    if is_idp:
        sub = str(claims["sub"])
        existing = next(
            (d for d in documents if str(d.get(collection.id_field, "")) == sub),
            None,
        )
        if existing is not None:
            if fk_fields:
                changed = {k: v for k, v in fk_fields.items() if existing.get(k) != v}
                if changed:
                    updated = await repo.update(collection.name, sub, changed)
                    return updated if updated is not None else {**existing, **changed}
            return existing
        if not binding.auto_provision:
            return None
        payload = {**user_fields, **fk_fields, collection.id_field: sub}
        return await repo.upsert_by(collection.name, collection.id_field, payload)

    identifier_value = user_fields.get(binding.identifier)
    existing = next(
        (d for d in documents if str(d.get(binding.identifier)) == str(identifier_value)),
        None,
    )
    if existing is not None:
        if fk_fields:
            existing_id = str(existing.get(collection.id_field, ""))
            changed = {k: v for k, v in fk_fields.items() if existing.get(k) != v}
            if changed:
                updated = await repo.update(collection.name, existing_id, changed)
                return updated if updated is not None else {**existing, **changed}
        return existing
    if binding.auto_provision:
        payload = {**user_fields, **fk_fields, collection.id_field: generate_id(collection.id_format)}
        return await repo.upsert_by(collection.name, binding.identifier, payload)
    return None


async def issue_login_code(
    claims: dict[str, Any],
    binding: IRProviderBinding,
    collection: RuntimeCollectionDescriptor,
    repo: BaseRepository,
    collections: dict[str, RuntimeCollectionDescriptor],
    registry: RepositoryRegistry | None,
) -> str:
    """Resolve the signed-in record and issue the one-time code the frontend exchanges for a session."""
    record = await resolve_record(claims, binding, collection, repo, collections=collections, registry=registry)
    if record is None:
        raise HTTPException(status_code=403, detail="User not found and auto-provisioning is disabled")
    return login_codes.issue(str(record.get(collection.id_field)), collection.name)
