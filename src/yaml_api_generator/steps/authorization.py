from typing import Callable

from . import Step

from ..context import RequestContext

from ..ir import IRIdentityCollection


class UnauthorizedError(ValueError):
    pass


class ForbiddenError(ValueError):
    pass


def _required_identity_fields(
    identity_collection: IRIdentityCollection,
) -> tuple[str, ...]:
    fields: list[str] = []
    if identity_collection.identifier:
        fields.append(identity_collection.identifier)

    for method in identity_collection.via:
        if method == "password":
            fields.append("password")
        elif method == "apiKey":
            fields.append("apiKey")
        else:
            raise ValueError(f"Unsupported auth method: {method}")

    unique_fields: list[str] = []
    for field_name in fields:
        if field_name and field_name not in unique_fields:
            unique_fields.append(field_name)
    return tuple(unique_fields)


def ValidateIdentityCreateStep(
    identity_collection: IRIdentityCollection,
) -> Step:
    required_fields = _required_identity_fields(identity_collection)

    def step(ctx: RequestContext) -> RequestContext:
        if ctx.collection != identity_collection.name or ctx.operation != "create":
            return ctx
        if not isinstance(ctx.body, dict):
            raise ValueError("Request body must be a JSON object")
        missing_fields = [
            field_name
            for field_name in required_fields
            if not isinstance(ctx.body.get(field_name), str)
            or not ctx.body[field_name].strip()
        ]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
        return ctx

    return step


def AuthorizeRouteStep() -> Step:
    def step(ctx: RequestContext) -> RequestContext:
        if ctx.principal is None:
            raise UnauthorizedError("Unauthorized")
        return ctx

    return step


IdentityStep = ValidateIdentityCreateStep
