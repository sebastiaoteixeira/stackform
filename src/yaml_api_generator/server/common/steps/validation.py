"""Request body validation pipeline step."""

from typing import Any

from yaml_api_generator.ir import SECRET_FIELD, IRDto, writable_fields
from yaml_api_generator.runtime.fields import NOT_AN_OBJECT, conform_object

from ..request_context import RequestContext
from ..server_context import RuntimeCollectionDescriptor, RuntimeIdentityDescriptor
from . import Step


_NO_BODY_OPS = frozenset({"list", "get", "delete"})


def credential_properties(
    operation: str, identity_collection: RuntimeIdentityDescriptor | None
) -> dict[str, dict[str, Any]]:
    """The properties a write operation takes besides the entity's writable fields."""
    if (
        identity_collection is not None
        and operation == "create"
        and identity_collection.has_password
    ):
        return {"password": SECRET_FIELD}
    return {}


def login_properties(
    identity_collection: RuntimeIdentityDescriptor,
) -> dict[str, dict[str, Any]]:
    binding = identity_collection.get_binding("password")
    identifier = binding.identifier if binding and binding.identifier else "identifier"
    return {identifier: SECRET_FIELD, "password": SECRET_FIELD}


def ValidateBodyStep(
    collection: RuntimeCollectionDescriptor,
    operation: str,
    identity_collection: RuntimeIdentityDescriptor | None = None,
    dto: IRDto | None = None,
) -> Step:
    """Check the body against ``dto`` when the route types it, else against the entity."""
    if operation in _NO_BODY_OPS:
        return lambda ctx: ctx
    if operation == "login":
        if identity_collection is None:
            raise ValueError("login operation requires an identity collection")
        properties = login_properties(identity_collection)
    elif dto is not None:
        properties = writable_fields(dto.fields)
    else:
        properties = {
            **credential_properties(operation, identity_collection),
            **writable_fields(collection.fields, collection.files),
        }
    partial = operation == "update" and dto is None
    files = set(collection.files)

    def step(ctx: RequestContext) -> RequestContext:
        body = ctx.body
        if not isinstance(body, dict):
            raise ValueError(NOT_AN_OBJECT)
        uploads = {name: value for name, value in body.items() if name in files}
        fields = {name: value for name, value in body.items() if name not in files}
        ctx.body = {**conform_object(properties, fields, partial=partial), **uploads}
        return ctx

    return step
