from typing import Awaitable, Callable

from ..request_context import RequestContext

Step = Callable[[RequestContext], RequestContext | Awaitable[RequestContext]]


class NotFoundError(ValueError):
    pass


from .authentication import ResolvePrincipalStep
from .authorization import (
    AuthorizeRouteStep,
    ForbiddenError,
    IdentityStep,
    PostFetchAuthorizeStep,
    ResolveWhereBindingsStep,
    UnauthorizedError,
    ValidateIdentityCreateStep,
)
from .login import LoginStep
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
    "ServiceInputStep",
    "Step",
    "NotFoundError",
    "ResolvePrincipalStep",
    "AuthorizeRouteStep",
    "PostFetchAuthorizeStep",
    "ResolveWhereBindingsStep",
    "ValidateIdentityCreateStep",
    "IdentityStep",
    "UnauthorizedError",
    "ForbiddenError",
    "LoginStep",
    "ValidateBodyStep",
    "RepositoryListStep",
    "RepositoryGetStep",
    "RepositoryCreateStep",
    "RepositoryUpdateStep",
    "RepositoryReplaceStep",
    "RepositoryDeleteStep",
    "RepositoryOperationStep",
]
