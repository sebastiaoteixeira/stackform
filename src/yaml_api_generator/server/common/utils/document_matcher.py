from typing import Any

from ..auth import verify_password


def find_document_with_password(
    documents: list[dict[str, Any]],
    identifier_field: str,
    identifier_value: str,
    password: str,
) -> dict[str, Any] | None:
    """Find a document that matches the identifier and passes bcrypt password verification.

    Expects the stored hash at ``_auth.passwordHash``.
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
