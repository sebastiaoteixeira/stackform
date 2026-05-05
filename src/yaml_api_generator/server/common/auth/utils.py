"""Authentication helper utilities."""

import base64

from ..steps.authorization import UnauthorizedError


def extract_bearer_token(headers: dict[str, str]) -> str | None:
    """Extract bearer token from Authorization header.

    Args:
        headers: HTTP headers dict

    Returns:
        Token string if found, None otherwise
    """
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return token if token else None


def extract_api_key(headers: dict[str, str]) -> str | None:
    """Extract API key from X-API-Key header or bearer token.

    Args:
        headers: HTTP headers dict

    Returns:
        API key if found, None otherwise
    """
    api_key = headers.get("X-API-Key") or headers.get("x-api-key")
    if api_key:
        return api_key
    return extract_bearer_token(headers)


def extract_basic_credentials(headers: dict[str, str]) -> tuple[str, str] | None:
    """Extract username and password from Basic auth header.

    Args:
        headers: HTTP headers dict

    Returns:
        Tuple of (username, password) if found, None if no Basic auth header

    Raises:
        UnauthorizedError: If Basic auth header is malformed
    """
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if not auth.lower().startswith("basic "):
        return None

    try:
        encoded = auth[6:].strip()
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception:
        raise UnauthorizedError("Invalid Basic auth encoding")

    if ":" not in decoded:
        raise UnauthorizedError("Invalid Basic auth format")

    username, password = decoded.split(":", 1)

    if not username:
        raise UnauthorizedError("Username cannot be empty")
    if not password:
        raise UnauthorizedError("Password cannot be empty")

    return (username, password)