"""Backend code generation context builders.

Orchestrates specialized builders to convert IR into compilation context.
"""

from typing import Any

from yaml_api_generator.ir import IRDocument
from ..compile_context import AppConfig, CompileContext, CorsConfig

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

    def build_context(self, document: IRDocument) -> CompileContext:
        """Build compilation context from IR document.

        Args:
            document: Complete IR document

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
        model_index = {m.name: m for m in models}
        routes = self._route.build_routes(document, model_index)

        raw_collections: dict[str, Any] = {}
        for name, col in document.collections.items():
            raw_collections[name] = {
                "id_field": col.idField,
                "id_format": col.idFormat,
                "type": col.type,
                "fields": col.fields,
            }

        auth = self._auth.build_auth_config(identity_map, document.collections, document.providers)
        repository_operations = self._repository.build_repository_operations(document.repositories)

        return CompileContext(
            app=app,
            models=models,
            routes=routes,
            auth=auth,
            collections=raw_collections,
            repository_operations=repository_operations,
        )


def build_context(document: IRDocument) -> CompileContext:
    """Build compilation context from IR document (functional interface).

    Args:
        document: Complete IR document

    Returns:
        Compilation context for code generation
    """
    builder = ContextBuilder()
    return builder.build_context(document)
