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


def create_jwt_token(sub: str, identity_collection: str) -> str:
    now = time.time()
    payload = {
        "sub": sub,
        "identity_collection": identity_collection,
        "iat": int(now),
        "exp": int(now + JWT_EXPIRATION_HOURS * 3600),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_jwt_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except (jwt.InvalidTokenError, Exception):
        return None
