import base64
from typing import Any

from ..auth import verify_password
from ..auth.jwt import decode_jwt_token
from ..context import RequestContext
from ..runtime_context import RuntimeIdentityDescriptor
from ..repositories import BaseRepository
from . import Step
from .authorization import UnauthorizedError


def ResolvePrincipalStep(
    identity_collections: dict[str, RuntimeIdentityDescriptor],
    identity_id_fields: dict[str, str],
    repository: BaseRepository,
) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        ctx.principal = await _resolve_identity_principal(
            identity_collections=identity_collections,
            identity_id_fields=identity_id_fields,
            repository=repository,
            headers=ctx.headers,
        )
        return ctx

    return step


def _extract_bearer_token(headers: dict[str, str]) -> str | None:
    authorization = headers.get("Authorization") or headers.get("authorization")
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        if token:
            return token
    return None


async def _resolve_jwt_principal(
    token: str,
    identity_collections: dict[str, RuntimeIdentityDescriptor],
    identity_id_fields: dict[str, str],
    repository: BaseRepository,
) -> dict[str, Any] | None:
    claims = decode_jwt_token(token)
    if claims is None:
        return None

    sub = claims.get("sub")
    collection_name = claims.get("identity_collection")
    if not sub or not collection_name:
        return None

    identity = identity_collections.get(collection_name)
    if identity is None or not identity.has_password:
        return None

    id_field = identity_id_fields.get(collection_name)
    if id_field is None:
        return None

    documents = await repository.list(collection_name)
    for doc in documents:
        if str(doc.get(id_field, "")) == sub:
            return _build_principal(
                doc,
                id_field=id_field,
                identity_collection=collection_name,
                identity=identity,
            )

    return None


async def _resolve_identity_principal(
    identity_collections: dict[str, RuntimeIdentityDescriptor],
    identity_id_fields: dict[str, str],
    repository: BaseRepository,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    bearer_token = _extract_bearer_token(headers)
    if bearer_token is not None:
        jwt_principal = await _resolve_jwt_principal(
            bearer_token,
            identity_collections,
            identity_id_fields,
            repository,
        )
        if jwt_principal is not None:
            return jwt_principal

    for identity in identity_collections.values():
        id_field = identity_id_fields.get(identity.name)
        if id_field is None:
            continue
        principal = await _resolve_identity_for_collection(
            identity,
            id_field,
            repository,
            headers,
        )
        if principal is not None:
            return principal
    return None


async def _resolve_identity_for_collection(
    identity: RuntimeIdentityDescriptor,
    id_field: str,
    repository: BaseRepository,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    if identity.has_api_key:
        token = _extract_api_key(headers)
        if token is not None:
            return await _find_principal(
                repository,
                collection_name=identity.name,
                field_name="_auth.apiKey",
                field_value=token,
                id_field=id_field,
                identity=identity,
            )

    pw_binding = identity.get_binding("password")
    if pw_binding is not None:
        credentials = _extract_basic_credentials(headers)
        if credentials is not None:
            identifier_value, password = credentials
            return await _find_principal_with_password(
                repository=repository,
                collection_name=identity.name,
                identifier_field=pw_binding.identifier,
                identifier_value=identifier_value,
                password=password,
                id_field=id_field,
                identity=identity,
            )

    return None


def _extract_api_key(headers: dict[str, str]) -> str | None:
    api_key = headers.get("X-API-Key") or headers.get("x-api-key")
    if api_key:
        token = api_key.strip()
        if token:
            return token

    authorization = headers.get("Authorization") or headers.get("authorization")
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        if token:
            return token

    return None


def _extract_basic_credentials(headers: dict[str, str]) -> tuple[str, str] | None:
    authorization = headers.get("Authorization") or headers.get("authorization")
    if authorization is None or not authorization.startswith("Basic "):
        return None

    encoded = authorization.removeprefix("Basic ").strip()
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception as exc:
        raise UnauthorizedError("Invalid basic authorization") from exc

    if ":" not in decoded:
        raise UnauthorizedError("Invalid basic authorization")

    username, password = decoded.split(":", 1)
    if not username or not password:
        raise UnauthorizedError("Invalid basic authorization")
    return username, password


async def _find_principal(
    repository: BaseRepository,
    collection_name: str,
    field_name: str,
    field_value: str,
    id_field: str,
    identity: RuntimeIdentityDescriptor,
) -> dict[str, Any] | None:
    documents = await repository.list(collection_name)
    for document in documents:
        # Support dotted field paths like _auth.apiKey
        actual_value = _get_nested(document, field_name)
        if str(actual_value or "") != field_value:
            continue
        return _build_principal(
            document,
            id_field=id_field,
            identity_collection=collection_name,
            identity=identity,
        )
    return None


def _get_nested(document: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    current: Any = document
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


async def _find_principal_with_password(
    repository: BaseRepository,
    collection_name: str,
    identifier_field: str,
    identifier_value: str,
    password: str,
    id_field: str,
    identity: RuntimeIdentityDescriptor,
) -> dict[str, Any] | None:
    documents = await repository.list(collection_name)
    for document in documents:
        if str(document.get(identifier_field, "")) != identifier_value:
            continue
        stored_hash = document["_auth"]["passwordHash"]
        if not isinstance(stored_hash, str):
            continue
        if not verify_password(password, stored_hash):
            continue
        return _build_principal(
            document,
            id_field=id_field,
            identity_collection=collection_name,
            identity=identity,
        )
    return None


def _build_principal(
    document: dict[str, Any],
    id_field: str,
    identity_collection: str,
    identity: RuntimeIdentityDescriptor | None = None,
) -> dict[str, Any]:
    subject = document.get(id_field)
    if subject is None:
        raise UnauthorizedError(
            f"Identity record missing canonical id field: {id_field}"
        )

    record = {k: v for k, v in document.items() if k != "_auth"}
    record.pop("password", None)

    principal: dict[str, Any] = {
        "sub": str(subject),
        "identity_collection": identity_collection,
        "record": record,
    }

    # Use configured roles_field if available
    roles_field = identity.roles_field if identity is not None else None
    if roles_field is not None:
        roles = document.get(roles_field)
    else:
        roles = document.get("roles") or document.get("role")

    if isinstance(roles, list):
        principal["roles"] = [str(role) for role in roles]
    elif isinstance(roles, str):
        principal["roles"] = [roles]
    return principal
