from typing import Awaitable, Callable

from ..request_context import RequestContext

Step = Callable[[RequestContext], RequestContext | Awaitable[RequestContext]]


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
