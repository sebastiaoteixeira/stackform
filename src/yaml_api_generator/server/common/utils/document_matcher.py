from typing import Any

from ..auth import verify_password


def find_document_with_password(
    documents: list[dict[str, Any]],
    identifier_field: str,
    identifier_value: str,
    password: str,
) -> dict[str, Any] | None:
    """
    Find document matching identifier and password.

    Searches through documents for one that:
    1. Has matching identifier field value
    2. Has valid password hash in _auth.passwordHash
    3. Password verification succeeds

    Args:
        documents: List of documents to search
        identifier_field: Field name to match (e.g., "email", "username")
        identifier_value: Expected value for identifier field
        password: Plain text password to verify

    Returns:
        Matching document if found, None otherwise

    Example:
        >>> docs = [{"email": "alice@example.com", "_auth": {"passwordHash": "..."}}]
        >>> find_document_with_password(docs, "email", "alice@example.com", "secret")
        {"email": "alice@example.com", ...}
    """
    for document in documents:
        if str(document.get(identifier_field, "")) != identifier_value:
            continue

        auth_data = document.get("_auth")
        if not isinstance(auth_data, dict):
            continue

        stored_hash = auth_data.get("passwordHash")
        if not isinstance(stored_hash, str):
            continue

        if not verify_password(password, stored_hash):
            continue

        return document

    return None
