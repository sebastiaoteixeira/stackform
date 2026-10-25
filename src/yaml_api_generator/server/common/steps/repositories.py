from dataclasses import dataclass
from typing import Any, cast

from ..auth import hash_api_key, hash_password
from ..request_context import RequestContext
from ..server_context import RuntimeIdentityDescriptor
from yaml_api_generator.ir.api import IRPagination
from yaml_api_generator.runtime.access import RoleHierarchies, Roles, conjoin, held_roles, matching
from yaml_api_generator.runtime.operations import (
    present,
    present_document as _inject_canonical_id,
    resolve,
)
from ..pagination import Page, build_response, map_request
from ..repositories.base import BaseRepository
from yaml_api_generator.runtime.ids import generate_id as _generate_id
from . import NotFoundError, Step
from .handlers import handler_request


_REQUEST_BODY_MESSAGE = "Request body must be a JSON object"
_NOT_FOUND_MESSAGE = "Resource not found"


def _repository(ctx: RequestContext) -> BaseRepository:
    return cast(BaseRepository, ctx.repository)


def _role_store(identity: RuntimeIdentityDescriptor | None) -> Roles:
    return identity.role_store if identity else Roles()


def _require_param(url_params: dict[str, str], token: str) -> str:
    value = url_params.get(token)
    if value is None:
        raise ValueError(f"Missing route parameter: {token}")
    return value


@dataclass(frozen=True)
class RecordLocator:
    """Locates the rows a route reaches from its path parameters.

    The record parameter names the record by its id field; each scope parameter
    constrains the same-named field.
    """

    id_field: str
    record_param: str | None = "id"
    scope: tuple[str, ...] = ()

    @property
    def is_scoped(self) -> bool:
        return bool(self.scope)

    def scope_criteria(self, url_params: dict[str, str]) -> dict[str, str]:
        return {name: _require_param(url_params, name) for name in self.scope}

    def document_id(self, url_params: dict[str, str]) -> str:
        return _require_param(url_params, self.record_param)

    def criteria(self, url_params: dict[str, str]) -> dict[str, Any]:
        return {**self.scope_criteria(url_params), self.id_field: self.document_id(url_params)}


async def _fetch_record(
    ctx: RequestContext, collection_name: str, locator: RecordLocator
) -> dict[str, Any] | None:
    if locator.is_scoped:
        return await _repository(ctx).find_one(
            collection_name, locator.criteria(ctx.url_params)
        )
    return await _repository(ctx).get(collection_name, locator.document_id(ctx.url_params))


def _record(ctx: RequestContext) -> dict[str, Any]:
    """The values a write stores: the body, overridden by those the authorizing rule binds."""
    if not isinstance(ctx.body, dict):
        raise ValueError(_REQUEST_BODY_MESSAGE)
    return {**ctx.body, **(ctx.bound_inputs or {})}


def _inject_canonical_id_list(
    documents: list[dict[str, Any]],
    id_field: str,
) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], _inject_canonical_id(document, id_field))
        for document in documents
    ]


def _prepare_payload(
    payload: dict[str, Any], identity: RuntimeIdentityDescriptor | None
) -> dict[str, Any]:
    normalized = dict(payload)

    if identity is not None and identity.has_password:
        raw_password = normalized.pop("password", None)
        if raw_password is not None:
            if not isinstance(raw_password, str) or not raw_password.strip():
                raise ValueError("Password must be a non-empty string")
            auth_data = normalized.get("_auth", {})
            if not isinstance(auth_data, dict):
                auth_data = {}
            auth_data["passwordHash"] = hash_password(raw_password)
            normalized["_auth"] = auth_data

    if identity is not None and identity.has_api_key and "apiKey" in normalized:
        normalized["apiKey"] = hash_api_key(normalized["apiKey"])

    return normalized


def RepositoryListStep(
    collection_name: str,
    id_field: str,
    pagination: IRPagination | None = None,
    locator: RecordLocator | None = None,
) -> Step:
    locator = locator or RecordLocator(id_field, None)

    async def step(ctx: RequestContext) -> RequestContext:
        rows = conjoin(ctx.row_filter, matching(locator.scope_criteria(ctx.url_params)))
        if pagination is None:
            result = await _repository(ctx).list(collection_name, rows)
            ctx.response = _inject_canonical_id_list(result, id_field)
            return ctx
        query = ctx.query or {}
        primitives = map_request(pagination, query)
        page = await _repository(ctx).paginate(collection_name, primitives, rows)
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
    identity: RuntimeIdentityDescriptor | None = None,
    hierarchies: RoleHierarchies | None = None,
    locator: RecordLocator | None = None,
) -> Step:
    """A new identity record keeps the roles it names only when its caller holds them;
    a new record holds the values of the path parameters scoping the route."""
    roles = _role_store(identity)
    locator = locator or RecordLocator(id_field, None)

    async def step(ctx: RequestContext) -> RequestContext:
        scoped = {**_record(ctx), **locator.scope_criteria(ctx.url_params)}
        granted = roles.granted(scoped, held_roles(ctx.principal, hierarchies or {}))
        payload = _prepare_payload(granted, identity)
        if id_format != "natural":
            payload[id_field] = _generate_id(id_format)
        result = await _repository(ctx).create(collection_name, payload)
        ctx.response = _inject_canonical_id(result, id_field)
        return ctx

    return step


def RepositoryUpdateStep(
    collection_name: str,
    id_field: str,
    locator: RecordLocator | None = None,
    *,
    identity: RuntimeIdentityDescriptor | None = None,
    hierarchies: RoleHierarchies | None = None,
) -> Step:
    roles = _role_store(identity)
    locator = locator or RecordLocator(id_field)

    async def step(ctx: RequestContext) -> RequestContext:
        revised = roles.revised(_record(ctx), held_roles(ctx.principal, hierarchies or {}))
        payload = _prepare_payload(revised, identity)
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
    locator: RecordLocator | None = None,
    *,
    identity: RuntimeIdentityDescriptor | None = None,
    hierarchies: RoleHierarchies | None = None,
) -> Step:
    roles = _role_store(identity)
    locator = locator or RecordLocator(id_field)

    async def step(ctx: RequestContext) -> RequestContext:
        revised = roles.revised(_record(ctx), held_roles(ctx.principal, hierarchies or {}))
        payload = _prepare_payload(revised, identity)
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
