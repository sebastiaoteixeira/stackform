"""Requests shared by in-process and generated-app HTTP tests."""

import jwt

_USER = {"email": "ttl@example.com", "password": "correct-horse-battery"}


def preflight(client, origin: str, path: str = "/api/posts") -> dict:
    response = client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )
    return {
        "status": response.status_code,
        "origin": response.headers.get("access-control-allow-origin"),
        "credentials": response.headers.get("access-control-allow-credentials"),
        "methods": response.headers.get("access-control-allow-methods"),
    }


def token_lifetime(client, base: str = "/api/users") -> int:
    """Register and log in a user, returning the access token's ``exp - iat`` in seconds."""
    client.post(f"{base}/register", json=_USER)
    token = client.post(f"{base}/login", json=_USER).json()["token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    return claims["exp"] - claims["iat"]


TOKEN_LIFETIME_PROBE = """
from tests.unit.support.http_probes import token_lifetime

with client:
    print(token_lifetime(client))
"""
