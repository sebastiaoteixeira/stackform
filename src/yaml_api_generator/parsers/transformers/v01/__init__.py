"""V0.1 YAML to IR transformation orchestrator.

Coordinates specialized transformers to convert v0.1 YAML specifications into IR objects.
"""

from dataclasses import replace
from typing import Any

from yaml_api_generator.ir import (
    IRApi,
    IRDocument,
    IRMongo,
    IRRepository,
    IRService,
)
from yaml_api_generator.parsers.yaml_parser import ConfigErrors

from .collection_transformer import CollectionTransformer
from .identity_transformer import IdentityTransformer
from .route_transformer import RouteTransformer


class V01Transformer:
    """Orchestrates v0.1 YAML to IR transformation."""

    def __init__(self):
        self._collection = CollectionTransformer()
        self._identity = IdentityTransformer()
        self._route = RouteTransformer()

    def transform(self, resolved: dict[str, Any]) -> IRDocument:
        """Transform v0.1 YAML specification to IR.

        Args:
            resolved: Fully resolved YAML specification dictionary

        Returns:
            Complete IRDocument with all components

        Raises:
            ConfigErrors: If any validation errors occur during transformation
        """
        api: dict[str, Any] = resolved.get("api", {})
        collections_data: dict[str, Any] = resolved["collections"]
        defaults = api.get("operations", {}).get("defaults", {})

        collections, collection_access_policies, id_field_errors = self._collection.transform(
            collections_data
        )
        if id_field_errors:
            raise ConfigErrors(id_field_errors)

        identity_collections = self._identity.transform(collections_data, collections)

        implicit_field_errors = self._identity.validate_implicit_auth_fields(
            collections, identity_collections
        )
        if implicit_field_errors:
            raise ConfigErrors(implicit_field_errors)

        routes = self._route.build_routes(
            collections_data,
            list(collections.keys()),
            collection_access_policies,
            identity_collections,
            defaults,
        )
        api_ir = IRApi(
            basePath=api.get("basePath", "/api"),
            version=api.get("version"),
        )
        route_prefix = api_ir.basePath.rstrip("/")
        if api_ir.version:
            route_prefix = f"{route_prefix}/{api_ir.version}"
        repositories = {
            name: IRRepository(name=name, entity=collection.entity_name)
            for name, collection in collections.items()
        }
        services = {
            f"{route.operation}-{route.collection}": IRService(
                name=f"{route.operation}-{route.collection}",
                repository=route.collection,
                operation=route.operation,
            )
            for route in routes
            if route.collection is not None
        }
        routes = [
            replace(
                route,
                path=f"{route_prefix}{route.path}",
                service=f"{route.operation}-{route.collection}",
            )
            if route.collection is not None
            else route
            for route in routes
        ]

        mongo_data = resolved.get("mongo", {})
        return IRDocument(
            version=str(resolved["version"]),
            api=api_ir,
            collections=collections,
            repositories=repositories,
            services=services,
            routes=routes,
            identityCollections=identity_collections,
            mongo=IRMongo(
                uri=mongo_data.get("uri", "mongodb://localhost:27017"),
                database=mongo_data.get("database", "yaml_api"),
            ),
        )
