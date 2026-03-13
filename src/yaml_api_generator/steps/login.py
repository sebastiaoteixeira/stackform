from typing import Any

from ..auth.jwt import create_jwt_token
from ..auth.password import verify_password
from ..context import RequestContext
from ..ir import IRIdentityCollection
from ..repositories import BaseRepository
from . import Step
from .authorization import UnauthorizedError


def LoginStep(
    identity_collection: IRIdentityCollection,
    id_field: str,
    repository: BaseRepository,
) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        body = ctx.body
        if not isinstance(body, dict):
            raise UnauthorizedError("Invalid login payload")

        identifier_value = body.get(identity_collection.identifier or "")
        password = body.get("password")
        if not identifier_value or not password:
            raise UnauthorizedError("Invalid credentials")

        documents = await repository.list(identity_collection.name)
        user = _find_user(
            documents,
            identifier_field=identity_collection.identifier or "",
            identifier_value=str(identifier_value),
            password=str(password),
        )
        if user is None:
            raise UnauthorizedError("Invalid credentials")

        subject = user.get(id_field)
        if subject is None:
            raise UnauthorizedError("Identity record missing id field")

        token = create_jwt_token(str(subject), identity_collection.name)

        safe_user = {
            k: v
            for k, v in user.items()
            if k not in ("password", "passwordHash", "_id")
        }

        ctx.response = {"token": token, "user": safe_user}
        return ctx

    return step


def _find_user(
    documents: list[dict[str, Any]],
    identifier_field: str,
    identifier_value: str,
    password: str,
) -> dict[str, Any] | None:
    for doc in documents:
        if str(doc.get(identifier_field, "")) != identifier_value:
            continue
        stored_hash = doc.get("passwordHash")
        if not isinstance(stored_hash, str):
            continue
        if not verify_password(password, stored_hash):
            continue
        return doc
    return None
