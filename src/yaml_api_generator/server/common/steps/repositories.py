import uuid
from typing import Any, cast

from ..auth import hash_password
from ..request_context import RequestContext
from yaml_api_generator.ir.api import IRRolesConfig
from ..repositories.base import BaseRepository
from . import NotFoundError, Step


_MISSING_ID_MESSAGE = "Missing route parameter: id"
_REQUEST_BODY_MESSAGE = "Request body must be a JSON object"
_NOT_FOUND_MESSAGE = "Resource not found"


def _repository(ctx: RequestContext) -> BaseRepository:
    return cast(BaseRepository, ctx.repository)


def _document_id(ctx: RequestContext) -> str:
    document_id = ctx.url_params.get("id")
    if document_id is None:
        raise ValueError(_MISSING_ID_MESSAGE)
    return document_id


def _payload(ctx: RequestContext) -> dict[str, Any]:
    if not isinstance(ctx.body, dict):
        raise ValueError(_REQUEST_BODY_MESSAGE)
    return cast(dict[str, Any], ctx.body)


def _inject_canonical_id(
    document: dict[str, Any] | None,
    id_field: str,
) -> dict[str, Any] | None:
    if document is None:
        return None
    normalized = dict(document)
    if id_field not in normalized and normalized.get("_id") is not None:
        normalized[id_field] = str(normalized["_id"])
    if id_field != "_id":
        normalized.pop("_id", None)
    normalized.pop("_auth", None)
    normalized.pop("password", None)
    return normalized


def _inject_canonical_id_list(
    documents: list[dict[str, Any]],
    id_field: str,
) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], _inject_canonical_id(document, id_field))
        for document in documents
    ]


def _generate_id(id_format: str) -> str:
    if id_format == "uuidv7":
        uuid7 = getattr(uuid, "uuid7", None)
        if uuid7 is None:
            raise RuntimeError("uuidv7 is not available in this Python runtime")
        return str(uuid7())
    if id_format == "uuidv4":
        return str(uuid.uuid4())
    raise ValueError(f"Unsupported id format: {id_format}")


def _prepare_payload(
    payload: dict[str, Any],
    *,
    password_via: bool,
    roles_config: IRRolesConfig | None = None,
    is_create: bool = False,
) -> dict[str, Any]:
    normalized = dict(payload)

    # Roles are managed exclusively through _auth namespace — never writable via CRUD
    normalized.pop("roles", None)
    normalized.pop("role", None)

    if password_via:
        raw_password = normalized.pop("password", None)
        if raw_password is not None:
            if not isinstance(raw_password, str) or not raw_password.strip():
                raise ValueError("Password must be a non-empty string")
            auth_data = normalized.get("_auth", {})
            if not isinstance(auth_data, dict):
                auth_data = {}
            auth_data["passwordHash"] = hash_password(raw_password)
            normalized["_auth"] = auth_data

    if is_create and roles_config is not None:
        auth_data = normalized.get("_auth", {})
        if not isinstance(auth_data, dict):
            auth_data = {}
        auth_data["roles"] = roles_config.default
        normalized["_auth"] = auth_data

    return normalized


def RepositoryListStep(collection_name: str, id_field: str) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        result = await _repository(ctx).list(collection_name)
        ctx.response = _inject_canonical_id_list(result, id_field)
        return ctx

    return step


def RepositoryGetStep(collection_name: str, id_field: str) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        result = await _repository(ctx).get(collection_name, _document_id(ctx))
        if result is None:
            raise NotFoundError(_NOT_FOUND_MESSAGE)
        ctx.response = _inject_canonical_id(result, id_field)
        return ctx

    return step


def RepositoryCreateStep(
    collection_name: str,
    id_field: str,
    id_format: str,
    password_via: bool,
    roles_config: IRRolesConfig | None = None,
) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        payload = _prepare_payload(
            _payload(ctx),
            password_via=password_via,
            roles_config=roles_config,
            is_create=True,
        )
        if id_format != "natural":
            payload[id_field] = _generate_id(id_format)
        result = await _repository(ctx).create(collection_name, payload)
        ctx.response = _inject_canonical_id(result, id_field)
        return ctx

    return step


def RepositoryUpdateStep(
    collection_name: str,
    id_field: str,
    password_via: bool,
) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        result = await _repository(ctx).update(
            collection_name,
            _document_id(ctx),
            _prepare_payload(_payload(ctx), password_via=password_via),
        )
        if result is None:
            raise NotFoundError(_NOT_FOUND_MESSAGE)
        ctx.response = _inject_canonical_id(result, id_field)
        return ctx

    return step


def RepositoryReplaceStep(
    collection_name: str,
    id_field: str,
    password_via: bool,
) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        result = await _repository(ctx).replace(
            collection_name,
            _document_id(ctx),
            _prepare_payload(_payload(ctx), password_via=password_via),
        )
        if result is None:
            raise NotFoundError(_NOT_FOUND_MESSAGE)
        ctx.response = _inject_canonical_id(result, id_field)
        return ctx

    return step


def RepositoryDeleteStep(collection_name: str, id_field: str) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        result = await _repository(ctx).delete(collection_name, _document_id(ctx))
        if result is None:
            raise NotFoundError(_NOT_FOUND_MESSAGE)
        ctx.response = _inject_canonical_id(result, id_field)
        return ctx

    return step


def RepositoryOperationStep(
    collection_name: str,
    query: dict[str, Any],
    id_field: str,
) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        bindings = {
            "principal": ctx.principal or {},
            "params": ctx.url_params,
            "body": ctx.body or {},
        }
        result = await _repository(ctx).run_operation(collection_name, query, bindings)
        ctx.response = _normalize_operation_result(result, id_field)
        return ctx

    return step


def _normalize_operation_result(result: Any, id_field: str) -> Any:
    if isinstance(result, list):
        if all(isinstance(item, dict) for item in result):
            return _inject_canonical_id_list(result, id_field)
        return result
    if isinstance(result, dict):
        return _inject_canonical_id(result, id_field)
    return result
