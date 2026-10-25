from inspect import isawaitable
from typing import Awaitable, Callable, Sequence

from ..request_context import RequestContext

Step = Callable[[RequestContext], RequestContext | Awaitable[RequestContext]]


def chain(steps: Sequence[Step]) -> Step:
    async def step(ctx: RequestContext) -> RequestContext:
        for current in steps:
            result = current(ctx)
            ctx = await result if isawaitable(result) else result
        return ctx

    return step


class NotFoundError(ValueError):
    pass


from ..repositories.base import ConflictError
from .authentication import ResolvePrincipalStep
from .authorization import (
    AuthorizeRouteStep,
    ForbiddenError,
    IdentityStep,
    PostFetchAuthorizeStep,
    ResolveAccessBindStep,
    ResolveWhereBindingsStep,
    UnauthorizedError,
    ValidateIdentityCreateStep,
)
from .handlers import HandlerStep
from .jwks import JWKSStep
from .login import LoginStep
from .refresh import RefreshStep
from .repositories import (
    RepositoryCreateStep,
    RepositoryDeleteStep,
    RepositoryGetStep,
    RepositoryListStep,
    RepositoryOperationStep,
    RepositoryReplaceStep,
    RepositoryUpdateStep,
)
from .services import ServiceInputStep
from .validation import ValidateBodyStep

__all__ = [
    "HandlerStep",
    "ServiceInputStep",
    "Step",
    "NotFoundError",
    "ConflictError",
    "ResolvePrincipalStep",
    "AuthorizeRouteStep",
    "PostFetchAuthorizeStep",
    "ResolveAccessBindStep",
    "ResolveWhereBindingsStep",
    "ValidateIdentityCreateStep",
    "IdentityStep",
    "UnauthorizedError",
    "ForbiddenError",
    "JWKSStep",
    "LoginStep",
    "RefreshStep",
    "ValidateBodyStep",
    "RepositoryListStep",
    "RepositoryGetStep",
    "RepositoryCreateStep",
    "RepositoryUpdateStep",
    "RepositoryReplaceStep",
    "RepositoryDeleteStep",
    "RepositoryOperationStep",
]
