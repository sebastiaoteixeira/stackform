"""Backend code generation context builders.

Orchestrates specialized builders to convert IR into compilation context.
"""

from typing import Any

from yaml_api_generator.ir import IRDocument, IRPostgres
from yaml_api_generator.server.common.loader import SchemaManagement
from ..compile_context import AppConfig, CompileContext, CorsConfig, SessionConfig

from .auth_builder import AuthBuilder
from .model_builder import ModelBuilder
from .repository_builder import RepositoryBuilder
from .route_builder import RouteBuilder


class ContextBuilder:
    """Orchestrates context building from IR document."""

    def __init__(self):
        self._model = ModelBuilder()
        self._route = RouteBuilder()
        self._auth = AuthBuilder()
        self._repository = RepositoryBuilder()

    def build_context(
        self, document: IRDocument, managed: SchemaManagement = SchemaManagement()
    ) -> CompileContext:
        """Build compilation context from IR document.

        Args:
            document: Complete IR document
            managed: Datastore families whose schema flows through migrations

        Returns:
            Compilation context for code generation
        """
        cors = None
        if document.api.cors:
            cors = CorsConfig(
                origins=document.api.cors.origins,
                methods=document.api.cors.methods,
                headers=document.api.cors.headers,
                credentials=document.api.cors.credentials,
            )

        app = AppConfig(
            base_path=document.api.basePath,
            api_version=document.api.version,
            cors=cors,
            port=document.api.port,
        )

        identity_map = document.identityCollections
        models = self._model.build_models(document.collections, identity_map, document.repositories)
        dto_models = self._model.build_dto_models(document.dtos)
        model_index = {m.name: m for m in models}
        routes = self._route.build_routes(document, model_index, document.dtos)

        raw_collections: dict[str, Any] = {}
        for name, col in document.collections.items():
            datastore = col.datastore or document.default_datastore
            ds = document.datastores.get(datastore)
            raw_collections[name] = {
                "id_field": col.idField,
                "id_format": col.idFormat,
                "type": col.type,
                "fields": col.fields,
                "datastore": datastore,
                "datastore_type": ds.type if ds is not None else "mongodb",
            }

        datastore_types = {n: c["datastore_type"] for n, c in raw_collections.items()}
        auth = self._auth.build_auth_config(
            identity_map, document.collections, document.providers, datastore_types
        )
        repository_operations = self._repository.build_repository_operations(document.repositories)

        datastores: dict[str, dict] = {}
        for name, ds in document.datastores.items():
            if isinstance(ds, IRPostgres):
                datastores[name] = {"type": ds.type, "dsn": ds.dsn}
            else:
                datastores[name] = {"type": ds.type, "uri": ds.uri, "database": ds.database}

        def _repo_datastore_type(repo) -> str:
            ds = document.datastores.get(repo.datastore) if repo.datastore else None
            return ds.type if ds is not None else "mongodb"

        repository_abstract = {
            repo.name: _repo_datastore_type(repo)
            for repo in document.repositories.values()
            if repo.abstract and repo.operations
        }
        repository_inherits = {
            repo.name: repo.inherits
            for repo in document.repositories.values()
            if repo.inherits
        }

        return CompileContext(
            app=app,
            models=models,
            routes=routes,
            auth=auth,
            collections=raw_collections,
            session=SessionConfig(
                algorithm=document.session.algorithm,
                ttl=document.session.ttl,
                refresh=document.session.refresh,
            ),
            repository_operations=repository_operations,
            datastores=datastores,
            repository_abstract=repository_abstract,
            repository_inherits=repository_inherits,
            services=dict(document.services),
            dto_models=dto_models,
            vendored_requirements=document.vendored_requirements,
            mongo_schema_managed=managed.mongo,
        )


def build_context(
    document: IRDocument, managed: SchemaManagement = SchemaManagement()
) -> CompileContext:
    """Build compilation context from IR document (functional interface).

    Args:
        document: Complete IR document
        managed: Datastore families whose schema flows through migrations

    Returns:
        Compilation context for code generation
    """
    builder = ContextBuilder()
    return builder.build_context(document, managed)
