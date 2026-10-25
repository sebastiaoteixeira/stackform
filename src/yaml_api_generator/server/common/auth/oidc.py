"""OIDC login flow for the dev server, mirroring the generated oidc_routes."""

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from yaml_api_generator.runtime.dpop import DPoPProofFactory, request_with_dpop
from yaml_api_generator.ir.api import IROIDCProvider
from ..utils.ttl_cache import TTLCache

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


async def fetch_claims(
    provider: IROIDCProvider,
    code: str,
    callback_url: str,
    *,
    code_verifier: str | None = None,
    dpop: DPoPProofFactory | None = None,
) -> dict[str, Any]:
    """Redeem the authorization code and return the signed-in user's userinfo claims."""
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
    return claims


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
