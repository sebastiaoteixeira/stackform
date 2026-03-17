import importlib

from .runtime_context import RuntimeContext, RuntimeRouteDescriptor
from .pipeline import Pipeline
from .repositories import BaseRepository
from .steps import (
    AuthorizeRouteStep,
    LoginStep,
    RepositoryCreateStep,
    RepositoryDeleteStep,
    RepositoryGetStep,
    RepositoryListStep,
    RepositoryReplaceStep,
    ResolvePrincipalStep,
    RepositoryUpdateStep,
    Step,
    ValidateBodyStep,
    ValidateIdentityCreateStep,
)


def _import_handler(dotted_path: str) -> Step:
    module_path, _, attr_name = dotted_path.rpartition(".")
    if not module_path:
        raise ValueError(f"Invalid handler path: {dotted_path}")
    module = importlib.import_module(module_path)
    handler = getattr(module, attr_name)
    return handler


class PipelineBuilder:
    def __init__(self, ctx: RuntimeContext, repository: BaseRepository) -> None:
        self._ctx = ctx
        self._repository = repository

    def build_for_route(self, route: RuntimeRouteDescriptor) -> Pipeline:
        if route.handler is not None:
            return self._build_handler_pipeline(route)

        if route.operation == "login":
            identity = self._ctx.auth.identity_collections.get(route.collection)
            collection = self._ctx.collections[route.collection]
            return Pipeline(
                steps=[
                    ValidateBodyStep(collection, "login", identity),
                    LoginStep(identity, collection.id_field, self._repository),
                ],
                method=route.method,
                path=route.path,
                api_version=self._ctx.app.api_version,
                collection=route.collection,
                operation=route.operation,
                repository=self._repository,
            )

        steps = self._base_steps(route)
        identity_step = self._identity_step(route)
        if identity_step is not None:
            steps.append(identity_step)
        steps.append(self._validate_body_step(route))
        steps.append(self._repository_step(route.operation, route.collection))
        return Pipeline(
            steps=steps,
            method=route.method,
            path=route.path,
            api_version=self._ctx.app.api_version,
            collection=route.collection,
            operation=route.operation,
            repository=self._repository,
        )

    def _build_handler_pipeline(self, route: RuntimeRouteDescriptor) -> Pipeline:
        steps: list[Step] = self._base_steps(route)
        handler_step = _import_handler(route.handler)
        steps.append(handler_step)
        return Pipeline(
            steps=steps,
            method=route.method,
            path=route.path,
            api_version=self._ctx.app.api_version,
            collection=route.collection,
            operation=route.operation,
            repository=self._repository,
        )

    def _base_steps(self, route: RuntimeRouteDescriptor) -> list[Step]:
        steps: list[Step] = []

        if not route.is_public and self._ctx.auth.identity_collections:
            steps.append(
                ResolvePrincipalStep(
                    self._ctx.auth.identity_collections,
                    self._ctx.auth.identity_id_fields,
                    self._repository,
                )
            )

        if not route.is_public:
            steps.append(AuthorizeRouteStep())

        return steps

    def _validate_body_step(self, route: RuntimeRouteDescriptor) -> Step:
        collection = self._ctx.collections[route.collection]
        identity_collection = self._ctx.auth.identity_collections.get(route.collection)
        return ValidateBodyStep(collection, route.operation, identity_collection)

    def _identity_step(self, route: RuntimeRouteDescriptor) -> Step | None:
        identity_collection = self._ctx.auth.identity_collections.get(route.collection)
        if identity_collection is None or route.operation != "create":
            return None
        return ValidateIdentityCreateStep(identity_collection)

    def _repository_step(self, operation: str, collection_name: str) -> Step:
        collection = self._ctx.collections[collection_name]
        id_field = collection.id_field
        identity_collection = self._ctx.auth.identity_collections.get(collection_name)
        uses_password = (
            identity_collection is not None and "password" in identity_collection.via
        )

        if operation == "list":
            return RepositoryListStep(collection_name, id_field)
        if operation == "get":
            return RepositoryGetStep(collection_name, id_field)
        if operation == "create":
            return RepositoryCreateStep(
                collection_name,
                id_field,
                collection.id_format,
                uses_password,
            )
        if operation == "update":
            return RepositoryUpdateStep(collection_name, id_field, uses_password)
        if operation == "replace":
            return RepositoryReplaceStep(collection_name, id_field, uses_password)
        if operation == "delete":
            return RepositoryDeleteStep(collection_name, id_field)
        raise ValueError(f"Unsupported operation: {operation}")
