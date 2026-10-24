import importlib
from collections.abc import Iterator, Mapping

from yaml_api_generator.ir import IRDocumentBinding
from .auth.session_tokens import SessionTokens
from yaml_api_generator.runtime.files import RecordFiles
from .server_context import RuntimeContext, RuntimeFileRouteDescriptor, RuntimeRouteDescriptor
from .pipeline import Pipeline
from .repositories import RepositoryRegistry
from .steps import (
    AuthorizeRouteStep,
    JWKSStep,
    LoginStep,
    PostFetchAuthorizeStep,
    ResolveAccessBindStep,
    RepositoryCreateStep,
    RepositoryDeleteStep,
    RepositoryGetStep,
    RepositoryListStep,
    RepositoryOperationStep,
    RepositoryReplaceStep,
    RefreshStep,
    RepositoryUpdateStep,
    ResolvePrincipalStep,
    ResolveWhereBindingsStep,
    ServiceInputStep,
    Step,
    ValidateBodyStep,
    ValidateIdentityCreateStep,
    chain,
)
from .steps.files import (
    DiscardFilesStep,
    DownloadFileStep,
    FileWriteStep,
    ingest_upload,
    remove_file,
    replace_file,
)
from .steps.repositories import RecordLocator, record_locator


def _document_bindings(route: RuntimeRouteDescriptor) -> Iterator[IRDocumentBinding]:
    return (
        binding
        for rule in route.access_rules or ()
        for binding in rule.document_symbols.values()
    )


def _has_access_bind(route: RuntimeRouteDescriptor) -> bool:
    return bool(route.access_rules) and any(rule.bind for rule in route.access_rules)


_CRUD_OPS = frozenset({"list", "get", "create", "update", "replace", "delete"})
_FILE_WRITE_OPS = frozenset({"create", "update", "replace"})
_FETCH_FIRST_OPS = frozenset({"update", "replace", "delete"})

_FILE_STEPS = {
    "download": lambda files, field, _write: DownloadFileStep(files, field),
    "replace": lambda files, field, write: FileWriteStep(files, replace_file(field), write),
    "remove": lambda files, field, write: FileWriteStep(files, remove_file(field), write),
}


def _import_handler(dotted_path: str) -> Step:
    module_path, _, attr_name = dotted_path.rpartition(".")
    if not module_path:
        raise ValueError(f"Invalid handler path: {dotted_path}")
    module = importlib.import_module(module_path)
    handler = getattr(module, attr_name)
    return handler


class PipelineBuilder:
    def __init__(
        self,
        ctx: RuntimeContext,
        registry: RepositoryRegistry,
        files: Mapping[str, RecordFiles] | None = None,
    ) -> None:
        self._ctx = ctx
        self._registry = registry
        self._files = files or {}
        self._tokens = SessionTokens(ctx.session)
        for name, col in ctx.collections.items():
            registry.for_collection(name).register_id_field(name, col.id_field)

    @property
    def tokens(self) -> SessionTokens:
        return self._tokens

    def build_for_route(self, route: RuntimeRouteDescriptor) -> Pipeline:
        if route.handler is not None:
            return self._build_handler_pipeline(route)

        repository = self._registry.for_collection(route.collection)

        if route.operation == "refresh":
            return Pipeline(
                steps=[RefreshStep(self._tokens)],
                method=route.method,
                path=route.path,
                api_version=self._ctx.app.api_version,
                collection=route.collection,

                operation=route.operation,
                repository=repository,
                repositories=self._registry,
            )

        if route.operation == "jwks":
            return Pipeline(
                steps=[JWKSStep(self._tokens)],
                method=route.method,
                path=route.path,
                api_version=None,
                collection=None,
                operation=route.operation,
                repository=repository,
                repositories=self._registry,
            )

        if route.operation == "login":
            identity = self._ctx.auth.identity_collections.get(route.collection)
            collection = self._ctx.collections[route.collection]
            return Pipeline(
                steps=[
                    ValidateBodyStep(collection, "login", identity),
                    LoginStep(
                        identity,
                        collection.id_field,
                        repository,
                        self._tokens,
                    ),
                ],
                method=route.method,
                path=route.path,
                api_version=self._ctx.app.api_version,
                collection=route.collection,
                operation=route.operation,
                repository=repository,
                repositories=self._registry,
            )

        steps = self._base_steps(route) + self._write_steps(route)
        record_files = self._files.get(route.collection)
        if record_files is not None and route.operation == "delete":
            steps.append(DiscardFilesStep(record_files))
        return self._pipeline(route, steps)

    def build_for_file_route(self, route: RuntimeFileRouteDescriptor) -> Pipeline:
        source = route.source
        record_files = self._files[route.collection]
        file_step = _FILE_STEPS[route.action](
            record_files, route.field, chain([self._repository_step(source)])
        )
        return self._pipeline(
            source,
            [*self._base_steps(source), *self._fetch_steps(source), file_step],
            path=route.path,
        )

    def _pipeline(
        self, route: RuntimeRouteDescriptor, steps: list[Step], path: str | None = None
    ) -> Pipeline:
        return Pipeline(
            steps=steps,
            method=route.method,
            path=path or route.path,
            api_version=self._ctx.app.api_version,
            collection=route.collection,
            operation=route.operation,
            repository=self._registry.for_collection(route.collection),
            repositories=self._registry,
        )

    def _write_steps(self, route: RuntimeRouteDescriptor) -> list[Step]:
        body_steps = [
            step
            for step in (
                self._service_input_step(route),
                self._identity_step(route),
                self._validate_body_step(route) if route.operation in _CRUD_OPS else None,
            )
            if step is not None
        ]
        record_files = self._files.get(route.collection)
        if record_files is not None and route.operation in _FILE_WRITE_OPS:
            fetch_steps = self._fetch_steps(route) if route.operation != "create" else []
            write = FileWriteStep(
                record_files,
                ingest_upload,
                chain([*body_steps, self._repository_step(route)]),
            )
            return [*fetch_steps, write]

        post_fetch_step = self._post_fetch_authorize_step(route)
        if post_fetch_step is not None and route.operation in _FETCH_FIRST_OPS:
            return [*body_steps, *self._fetch_steps(route), self._repository_step(route)]
        return [
            *body_steps,
            self._repository_step(route),
            *([post_fetch_step] if post_fetch_step is not None else []),
        ]

    def _fetch_steps(self, route: RuntimeRouteDescriptor) -> list[Step]:
        post_fetch_step = self._post_fetch_authorize_step(route)
        fetch = RepositoryGetStep(
            route.collection,
            self._ctx.collections[route.collection].id_field,
            self._locator(route),
        )
        return [fetch, *([post_fetch_step] if post_fetch_step is not None else [])]

    def _build_handler_pipeline(self, route: RuntimeRouteDescriptor) -> Pipeline:
        steps: list[Step] = self._base_steps(route)
        service_input_step = self._service_input_step(route)
        if service_input_step is not None:
            steps.append(service_input_step)
        steps.append(_import_handler(route.handler))
        return self._pipeline(route, steps)

    def _base_steps(self, route: RuntimeRouteDescriptor) -> list[Step]:
        steps: list[Step] = []

        if not route.is_public and self._ctx.auth.identity_collections:
            steps.append(
                ResolvePrincipalStep(
                    self._ctx.auth.identity_collections,
                    self._ctx.auth.identity_id_fields,
                    self._registry,
                    self._ctx.auth.providers,
                    self._ctx.collections,
                    tokens=self._tokens,
                )
            )

        if not route.is_public and any(binding.where for binding in _document_bindings(route)):
            steps.append(ResolveWhereBindingsStep(route.access_rules))

        if not route.is_public:
            steps.append(AuthorizeRouteStep(route.access_rules, self._ctx.auth))

        if not route.is_public and _has_access_bind(route):
            steps.append(ResolveAccessBindStep(route.access_rules))

        return steps

    def _validate_body_step(self, route: RuntimeRouteDescriptor) -> Step:
        collection = self._ctx.collections[route.collection]
        identity_collection = self._ctx.auth.identity_collections.get(route.collection)
        return ValidateBodyStep(collection, route.operation, identity_collection, route.body_dto)

    def _service_input_step(self, route: RuntimeRouteDescriptor) -> Step | None:
        if route.service_input is None and not route.service_forwarding:
            return None
        return ServiceInputStep(route.service_input or {}, route.service_forwarding)

    def _identity_step(self, route: RuntimeRouteDescriptor) -> Step | None:
        identity_collection = self._ctx.auth.identity_collections.get(route.collection)
        if identity_collection is None or route.operation != "create":
            return None
        return ValidateIdentityCreateStep(identity_collection)

    def _post_fetch_authorize_step(self, route: RuntimeRouteDescriptor) -> Step | None:
        if route.is_public or not route.access_rules:
            return None
        if all(binding.where for binding in _document_bindings(route)):
            return None
        if route.operation not in ("get", "update", "replace", "delete"):
            return None
        return PostFetchAuthorizeStep(route.access_rules, self._ctx.auth)

    def _locator(self, route: RuntimeRouteDescriptor):
        if getattr(self._ctx, "spec_version", "0.2") != "0.3":
            return RecordLocator(self._ctx.collections[route.collection].id_field)
        return record_locator(
            route.path, self._ctx.collections[route.collection].id_field
        )

    def _repository_step(self, route: RuntimeRouteDescriptor) -> Step:
        collection_name = route.collection
        operation = route.operation
        collection = self._ctx.collections[collection_name]
        id_field = collection.id_field
        identity = self._ctx.auth.identity_collections.get(collection_name)

        if operation == "list":
            return RepositoryListStep(collection_name, id_field, route.pagination)
        if operation == "get":
            return RepositoryGetStep(collection_name, id_field, self._locator(route))
        if operation == "create":
            return RepositoryCreateStep(collection_name, id_field, collection.id_format, identity)
        if operation == "update":
            return RepositoryUpdateStep(
                collection_name, id_field, self._locator(route), identity=identity
            )
        if operation == "replace":
            return RepositoryReplaceStep(
                collection_name, id_field, self._locator(route), identity=identity
            )
        if operation == "delete":
            return RepositoryDeleteStep(collection_name, id_field, self._locator(route))

        descriptor = self._ctx.operations.get(collection_name, {}).get(operation)
        if descriptor is not None:
            if descriptor.query is not None:
                return RepositoryOperationStep(collection_name, descriptor.query, id_field)
            if descriptor.handler is not None:
                return _import_handler(descriptor.handler)
        raise ValueError(f"Unsupported operation: {operation}")
