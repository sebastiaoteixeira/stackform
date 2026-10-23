import re
from dataclasses import dataclass
from typing import Any, cast

from ..auth import hash_password
from ..request_context import RequestContext
from yaml_api_generator.ir.api import IRPagination, IRRolesConfig
from yaml_api_generator.runtime.operations import (
    present,
    present_document as _inject_canonical_id,
    resolve,
)
from ..pagination import Page, build_response, map_request
from ..repositories.base import BaseRepository
from ..utils.ids import generate_id as _generate_id
from . import NotFoundError, Step
from .handlers import handler_request


_PATH_TOKEN = re.compile(r"\{(\w+)\}")
_REQUEST_BODY_MESSAGE = "Request body must be a JSON object"
_NOT_FOUND_MESSAGE = "Resource not found"


def _repository(ctx: RequestContext) -> BaseRepository:
    return cast(BaseRepository, ctx.repository)


def _require_param(url_params: dict[str, str], token: str) -> str:
    value = url_params.get(token)
    if value is None:
        raise ValueError(f"Missing route parameter: {token}")
    return value


@dataclass(frozen=True)
class RecordLocator:
    """Locates a single record from a route's path tokens.

    The final path token identifies the record by its id field; each preceding
    token constrains a same-named field, scoping the record to its parents.
    """

    id_field: str
    id_token: str = "id"
    parents: tuple[tuple[str, str], ...] = ()

    @property
    def is_scoped(self) -> bool:
        return bool(self.parents)

    def document_id(self, url_params: dict[str, str]) -> str:
        return _require_param(url_params, self.id_token)

    def criteria(self, url_params: dict[str, str]) -> dict[str, Any]:
        constraints = {
            field_name: _require_param(url_params, token)
            for field_name, token in self.parents
        }
        constraints[self.id_field] = _require_param(url_params, self.id_token)
        return constraints


def record_locator(path: str, id_field: str) -> RecordLocator:
    *parents, id_token = _PATH_TOKEN.findall(path) or ["id"]
    return RecordLocator(
        id_field=id_field,
        id_token=id_token,
        parents=tuple((token, token) for token in parents),
    )


async def _fetch_record(
    ctx: RequestContext, collection_name: str, locator: RecordLocator
) -> dict[str, Any] | None:
    if locator.is_scoped:
        return await _repository(ctx).find_one(
            collection_name, locator.criteria(ctx.url_params)
        )
    return await _repository(ctx).get(collection_name, locator.document_id(ctx.url_params))


def _payload(ctx: RequestContext) -> dict[str, Any]:
    if not isinstance(ctx.body, dict):
        raise ValueError(_REQUEST_BODY_MESSAGE)
    return cast(dict[str, Any], ctx.body)


def _inject_canonical_id_list(
    documents: list[dict[str, Any]],
    id_field: str,
) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], _inject_canonical_id(document, id_field))
        for document in documents
    ]


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


def RepositoryListStep(
    collection_name: str,
    id_field: str,
    pagination: IRPagination | None = None,
) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        if pagination is None:
            result = await _repository(ctx).list(collection_name)
            ctx.response = _inject_canonical_id_list(result, id_field)
            return ctx
        query = ctx.query or {}
        primitives = map_request(pagination, query)
        page = await _repository(ctx).paginate(collection_name, primitives)
        canonical = Page(
            rows=_inject_canonical_id_list(page.rows, id_field),
            total=page.total,
        )
        ctx.response = build_response(pagination, canonical, query)
        return ctx

    return step


def RepositoryGetStep(
    collection_name: str, id_field: str, locator: RecordLocator | None = None
) -> Step:
    locator = locator or RecordLocator(id_field)

    async def step(ctx: RequestContext) -> RequestContext:
        result = await _fetch_record(ctx, collection_name, locator)
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
    locator: RecordLocator | None = None,
) -> Step:
    locator = locator or RecordLocator(id_field)

    async def step(ctx: RequestContext) -> RequestContext:
        payload = _prepare_payload(_payload(ctx), password_via=password_via)
        if locator.is_scoped:
            result = await _repository(ctx).update_by(
                collection_name, locator.criteria(ctx.url_params), payload
            )
        else:
            result = await _repository(ctx).update(
                collection_name, locator.document_id(ctx.url_params), payload
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
    locator: RecordLocator | None = None,
) -> Step:
    locator = locator or RecordLocator(id_field)

    async def step(ctx: RequestContext) -> RequestContext:
        payload = _prepare_payload(_payload(ctx), password_via=password_via)
        if locator.is_scoped:
            result = await _repository(ctx).replace_by(
                collection_name, locator.criteria(ctx.url_params), payload
            )
        else:
            result = await _repository(ctx).replace(
                collection_name, locator.document_id(ctx.url_params), payload
            )
        if result is None:
            raise NotFoundError(_NOT_FOUND_MESSAGE)
        ctx.response = _inject_canonical_id(result, id_field)
        return ctx

    return step


def RepositoryDeleteStep(
    collection_name: str, id_field: str, locator: RecordLocator | None = None
) -> Step:
    locator = locator or RecordLocator(id_field)

    async def step(ctx: RequestContext) -> RequestContext:
        if locator.is_scoped:
            result = await _repository(ctx).delete_by(
                collection_name, locator.criteria(ctx.url_params)
            )
        else:
            result = await _repository(ctx).delete(
                collection_name, locator.document_id(ctx.url_params)
            )
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
        bindings = handler_request(ctx).bindings
        result = await _repository(ctx).run_operation(collection_name, resolve(query, bindings))
        ctx.response = present(result, id_field)
        return ctx

    return step
