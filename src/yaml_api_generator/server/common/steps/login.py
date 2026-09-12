from typing import Any

from ..auth.jwt import SessionTokens
from ..request_context import RequestContext
from ..server_context import RuntimeIdentityDescriptor
from ..repositories import BaseRepository
from ..utils.document_matcher import find_document_with_password
from . import Step
from .authorization import UnauthorizedError


def LoginStep(
    identity_collection: RuntimeIdentityDescriptor,
    id_field: str,
    repository: BaseRepository,
    tokens: SessionTokens,
) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        body = ctx.body
        if not isinstance(body, dict):
            raise UnauthorizedError("Invalid login payload")

        pw_binding = identity_collection.get_binding("password")
        identifier_field = pw_binding.identifier if pw_binding else ""
        identifier_value = body.get(identifier_field)
        password = body.get("password")
        if not identifier_value or not password:
            raise UnauthorizedError("Invalid credentials")

        documents = await repository.list(identity_collection.name)
        user = find_document_with_password(
            documents,
            identifier_field=identifier_field,
            identifier_value=str(identifier_value),
            password=str(password),
        )
        if user is None:
            raise UnauthorizedError("Invalid credentials")

        subject = user.get(id_field)
        if subject is None:
            raise UnauthorizedError("Identity record missing id field")

        token = tokens.create(str(subject), identity_collection.name)

        safe_user = {
            k: v for k, v in user.items() if k not in ("password", "_id", "_auth")
        }

        ctx.response = {"token": token, "user": safe_user}
        return ctx

    return step
