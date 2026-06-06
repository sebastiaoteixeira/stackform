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
from .validation import ValidateBodyStep

__all__ = [
    "Step",
    "NotFoundError",
    "ResolvePrincipalStep",
    "AuthorizeRouteStep",
    "PostFetchAuthorizeStep",
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
