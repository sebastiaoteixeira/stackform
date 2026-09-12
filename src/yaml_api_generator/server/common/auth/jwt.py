"""HS256-signed JWT tokens with configurable expiration.

Environment:
- JWT_SECRET: signing secret (required in production)
- JWT_EXPIRATION_HOURS: token lifetime in hours (default: 24)
"""

import os
import time

import jwt


JWT_SECRET = os.environ.get("JWT_SECRET", "yaml-api-dev-secret-change-me")
JWT_EXPIRATION_HOURS = int(os.environ.get("JWT_EXPIRATION_HOURS", "24"))


def _encode(claims: dict, ttl_seconds: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {**claims, "iat": now, "exp": now + ttl_seconds}, JWT_SECRET, algorithm="HS256"
    )


def _decode(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None


def create_jwt_token(
    sub: str, identity_collection: str, ttl_seconds: int | None = None
) -> str:
    return _encode(
        {"sub": sub, "identity_collection": identity_collection},
        ttl_seconds if ttl_seconds is not None else JWT_EXPIRATION_HOURS * 3600,
    )


def decode_jwt_token(token: str) -> dict | None:
    claims = _decode(token)
    return None if claims is None or claims.get("typ") == "refresh" else claims


def create_refresh_token(
    sub: str, identity_collection: str, jti: str, sid: str, ttl_seconds: int
) -> str:
    return _encode(
        {
            "sub": sub,
            "identity_collection": identity_collection,
            "jti": jti,
            "sid": sid,
            "typ": "refresh",
        },
        ttl_seconds,
    )


def decode_refresh_token(token: str) -> dict | None:
    claims = _decode(token)
    return claims if claims and claims.get("typ") == "refresh" else None
