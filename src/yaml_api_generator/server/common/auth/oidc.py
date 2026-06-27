"""OIDC login flow for the dev server, mirroring the generated oidc_routes.

Discovery documents are fetched once per URL and cached. The flow resolves any
deferred env references at request time (the generated backend reads them from
its settings singleton instead).
"""

import os
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from yaml_api_generator.ir.api import EnvRef, IROIDCProvider, IRProviderBinding
from ..repositories import BaseRepository
from ..server_context import RuntimeCollectionDescriptor
from ..steps.repositories import _generate_id
from .login_codes import login_codes

_discovery_cache: dict[str, dict[str, Any]] = {}


def _resolve(value: str | EnvRef | None) -> str:
    if isinstance(value, EnvRef):
        resolved = os.environ.get(value.name, value.default)
        if resolved is None:
            raise RuntimeError(f"Environment variable '{value.name}' is required for an OIDC provider")
        return resolved
    if value is None:
        raise RuntimeError("OIDC provider is missing a required value")
    return value


async def _discovery(discovery_url: str) -> dict[str, Any]:
    if discovery_url not in _discovery_cache:
        async with httpx.AsyncClient() as client:
            resp = await client.get(discovery_url)
            resp.raise_for_status()
            _discovery_cache[discovery_url] = resp.json()
    return _discovery_cache[discovery_url]


async def build_login_redirect(provider: IROIDCProvider, callback_url: str) -> str:
    discovery = await _discovery(_resolve(provider.discovery_url))
    params = {
        "client_id": _resolve(provider.client_id),
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
    }
    return f"{discovery['authorization_endpoint']}?{urlencode(params)}"


async def build_logout_redirect(provider: IROIDCProvider, post_logout_redirect_uri: str) -> str:
    discovery = await _discovery(_resolve(provider.discovery_url))
    end_session = discovery.get("end_session_endpoint")
    if not end_session:
        raise HTTPException(status_code=501, detail="Provider does not support end-session logout")
    params = {
        "client_id": _resolve(provider.client_id),
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
) -> str:
    discovery = await _discovery(_resolve(provider.discovery_url))

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(discovery["token_endpoint"], data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url,
            "client_id": _resolve(provider.client_id),
            "client_secret": _resolve(provider.client_secret),
        })
        if token_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Token exchange failed")
        token_data = token_resp.json()

        userinfo_resp = await client.get(
            discovery.get("userinfo_endpoint", ""),
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to fetch user info")
        claims = userinfo_resp.json()

    exp = claims.get("exp")
    if exp is not None and int(exp) < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired")

    user_fields = {
        local_field: claims[oidc_claim]
        for local_field, oidc_claim in binding.claim_mapping.items()
        if oidc_claim in claims
    }
    if binding.identifier not in user_fields:
        user_fields[binding.identifier] = (
            claims.get("email") or claims.get("login") or claims.get("sub")
        )

    identifier_value = user_fields.get(binding.identifier)
    documents = await repo.list(collection.name)
    existing = next(
        (d for d in documents if str(d.get(binding.identifier)) == str(identifier_value)),
        None,
    )

    if existing is not None:
        subject = existing.get(collection.id_field)
    elif binding.auto_provision:
        payload = dict(user_fields)
        payload[collection.id_field] = _generate_id(collection.id_format)
        created = await repo.create(collection.name, payload)
        subject = created.get(collection.id_field)
    else:
        raise HTTPException(status_code=403, detail="User not found and auto-provisioning is disabled")

    return login_codes.issue(str(subject), collection.name)
