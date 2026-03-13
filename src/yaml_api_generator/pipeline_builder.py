from .ir import IRDocument, IRRoute
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


class PipelineBuilder:
    def __init__(self, document: IRDocument, repository: BaseRepository) -> None:
        self._document = document
        self._repository = repository

    def build_for_route(self, route: IRRoute) -> Pipeline:
        if route.operation == "login":
            identity = self._document.identityCollections.get(route.collection)
            collection = self._document.collections[route.collection]
            return Pipeline(
                steps=[
                    ValidateBodyStep(collection, "login", identity),
                    LoginStep(identity, collection.idField, self._repository),
                ],
                method=route.method,
                path=route.path,
                api_version=self._document.api.version,
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
            api_version=self._document.api.version,
            collection=route.collection,
            operation=route.operation,
            repository=self._repository,
        )

    def _base_steps(self, route: IRRoute) -> list[Step]:
        steps: list[Step] = []

        if not route.is_public and self._document.identityCollections:
            steps.append(
                ResolvePrincipalStep(
                    self._document.identityCollections,
                    {
                        name: collection.idField
                        for name, collection in self._document.collections.items()
                        if name in self._document.identityCollections
                    },
                    self._repository,
                )
            )

        if not route.is_public:
            steps.append(AuthorizeRouteStep())

        return steps

    def _validate_body_step(self, route: IRRoute) -> Step:
        collection = self._document.collections[route.collection]
        identity_collection = self._document.identityCollections.get(route.collection)
        return ValidateBodyStep(collection, route.operation, identity_collection)

    def _identity_step(self, route: IRRoute) -> Step | None:
        identity_collection = self._document.identityCollections.get(route.collection)
        if identity_collection is None or route.operation != "create":
            return None
        return ValidateIdentityCreateStep(identity_collection)

    def _repository_step(self, operation: str, collection_name: str) -> Step:
        collection = self._document.collections[collection_name]
        id_field = collection.idField
        identity_collection = self._document.identityCollections.get(collection_name)
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
                collection.idFormat,
                uses_password,
            )
        if operation == "update":
            return RepositoryUpdateStep(collection_name, id_field, uses_password)
        if operation == "replace":
            return RepositoryReplaceStep(collection_name, id_field, uses_password)
        if operation == "delete":
            return RepositoryDeleteStep(collection_name, id_field)
        raise ValueError(f"Unsupported operation: {operation}")
