"""OIDC login flow for the dev server, mirroring the generated oidc_routes."""

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from yaml_api_generator.dpop import DPoPProofFactory, request_with_dpop
from yaml_api_generator.ir.api import IROIDCProvider, IRProviderBinding, IRProviderRelation
from ..repositories import BaseRepository, RepositoryRegistry
from ..server_context import RuntimeCollectionDescriptor
from ..utils.ids import generate_id
from ..utils.field_access import resolve_claim_path
from ..utils.ttl_cache import TTLCache
from .login_codes import login_codes

_discovery_cache: TTLCache[str, dict[str, Any]] = TTLCache()


async def _discovery(discovery_url: str) -> dict[str, Any]:
    cached = _discovery_cache.get(discovery_url)
    if cached is not None:
        return cached
    async with httpx.AsyncClient() as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
    document: dict[str, Any] = resp.json()
    _discovery_cache[discovery_url] = document
    return document


def create_pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def build_login_redirect(
    provider: IROIDCProvider,
    callback_url: str,
    *,
    state: str,
    code_challenge: str | None = None,
) -> str:
    if not provider.discovery_url:
        raise RuntimeError(f"Provider '{provider.name}' is missing discovery_url")
    discovery = await _discovery(provider.discovery_url)
    params = {
        "client_id": provider.client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    if code_challenge is not None:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return f"{discovery['authorization_endpoint']}?{urlencode(params)}"


async def build_logout_redirect(provider: IROIDCProvider, post_logout_redirect_uri: str) -> str:
    if not provider.discovery_url:
        raise RuntimeError(f"Provider '{provider.name}' is missing discovery_url")
    discovery = await _discovery(provider.discovery_url)
    end_session = discovery.get("end_session_endpoint")
    if not end_session:
        raise HTTPException(status_code=501, detail="Provider does not support end-session logout")
    params = {
        "client_id": provider.client_id,
        "post_logout_redirect_uri": post_logout_redirect_uri,
    }
    return f"{end_session}?{urlencode(params)}"


async def handle_callback(
    provider: IROIDCProvider,
    binding: IRProviderBinding,
    collection: RuntimeCollectionDescriptor,
    repo: BaseRepository,
    code: str,
    callback_url: str,
    collections: dict[str, RuntimeCollectionDescriptor] | None = None,
    registry: RepositoryRegistry | None = None,
    code_verifier: str | None = None,
    dpop: DPoPProofFactory | None = None,
) -> str:
    if not provider.discovery_url:
        raise RuntimeError(f"Provider '{provider.name}' is missing discovery_url")
    discovery = await _discovery(provider.discovery_url)

    token_data = await _exchange_code(
        provider,
        discovery,
        code,
        callback_url,
        code_verifier=code_verifier,
        dpop=dpop,
    )
    if dpop is not None and token_data.get("token_type", "").lower() != "dpop":
        raise HTTPException(
            status_code=401,
            detail="Provider did not issue a DPoP-bound token",
        )
    claims = await _fetch_userinfo(
        discovery,
        token_data["access_token"],
        dpop=dpop,
    )

    exp = claims.get("exp")
    if exp is not None and int(exp) < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired")

    record = await resolve_record(claims, binding, collection, repo, collections=collections or {}, registry=registry)
    if record is None:
        raise HTTPException(status_code=403, detail="User not found and auto-provisioning is disabled")

    return login_codes.issue(str(record.get(collection.id_field)), collection.name)


async def _exchange_code(
    provider: IROIDCProvider,
    discovery: dict[str, Any],
    code: str,
    callback_url: str,
    *,
    code_verifier: str | None = None,
    dpop: DPoPProofFactory | None = None,
) -> dict[str, Any]:
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": callback_url,
        "client_id": provider.client_id,
    }
    if provider.client_secret:
        data["client_secret"] = provider.client_secret
    if code_verifier is not None:
        data["code_verifier"] = code_verifier
    async with httpx.AsyncClient() as client:
        if dpop is None:
            resp = await client.post(discovery["token_endpoint"], data=data)
        else:
            resp = await request_with_dpop(
                client,
                "POST",
                discovery["token_endpoint"],
                dpop,
                data=data,
            )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Token exchange failed")
    return resp.json()  # type: ignore[no-any-return]


async def _fetch_userinfo(
    discovery: dict[str, Any],
    access_token: str,
    *,
    dpop: DPoPProofFactory | None = None,
) -> dict[str, Any]:
    endpoint = discovery.get("userinfo_endpoint", "")
    scheme = "DPoP" if dpop is not None else "Bearer"
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"{scheme} {access_token}"}
        if dpop is None:
            resp = await client.get(endpoint, headers=headers)
        else:
            resp = await request_with_dpop(
                client,
                "GET",
                endpoint,
                dpop,
                access_token=access_token,
                headers=headers,
            )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Failed to fetch user info")
    return resp.json()  # type: ignore[no-any-return]


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
