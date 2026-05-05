from ..request_context import RequestContext
from . import Step
from .repositories import (
    RepositoryCreateStep,
    RepositoryDeleteStep,
    RepositoryGetStep,
    RepositoryListStep,
    RepositoryReplaceStep,
    RepositoryUpdateStep,
)


def CreateEntityStep(collection_name: str) -> Step:
    async def step(context: RequestContext) -> RequestContext:
        context.collection = collection_name
        return context

    return step


__all__ = [
    "CreateEntityStep",
    "RepositoryListStep",
    "RepositoryGetStep",
    "RepositoryCreateStep",
    "RepositoryUpdateStep",
    "RepositoryReplaceStep",
    "RepositoryDeleteStep",
]
