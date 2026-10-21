"""V0.1 YAML to IR transformation orchestrator.

Coordinates specialized transformers to convert v0.1 YAML specifications into IR objects.
"""

from dataclasses import replace
from typing import Any

from yaml_api_generator.ir import (
    IRApi,
    IRCors,
    IRDocument,
    IRMongo,
    IRPagination,
    IRRepository,
    IRService,
)
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors

from ..v02.datastore_transformer import DEFAULT_DATASTORE
from ..v03.pagination import parse_pagination

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
        api_ir = self._build_api(api, resolved.get("security", {}))
        pagination, pagination_errors = self._build_pagination(api.get("pagination", {}))
        if pagination_errors:
            raise ConfigErrors(pagination_errors)
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
                pagination=pagination if route.operation == "list" else None,
            )
            if route.collection is not None
            else route
            for route in routes
        ]

        mongo_data = resolved.get("mongo", {})
        mongo = IRMongo(
            uri=mongo_data.get("uri", IRMongo.uri),
            database=mongo_data.get("database", IRMongo.database),
        )
        return IRDocument(
            version=str(resolved["version"]),
            api=api_ir,
            collections=collections,
            repositories=repositories,
            services=services,
            routes=routes,
            identityCollections=identity_collections,
            mongo=mongo,
            datastores={DEFAULT_DATASTORE: mongo},
            default_datastore=DEFAULT_DATASTORE,
        )

    @staticmethod
    def _build_api(api: dict[str, Any], security: dict[str, Any]) -> IRApi:
        cors = security.get("cors")
        return IRApi(
            basePath=api.get("basePath", "/api"),
            version=api.get("version"),
            cors=None if cors is None else IRCors(
                origins=cors.get("allowedOrigins", []),
                methods=cors.get("allowedMethods", ["*"]),
                credentials=cors.get("allowCredentials", False),
            ),
            security_headers=security.get("headers", {}).get("enableStandard", True),
        )

    @staticmethod
    def _build_pagination(pagination: dict[str, Any]) -> tuple[IRPagination | None, list[ConfigError]]:
        maximum = pagination.get("maxPageSize", 100)
        return parse_pagination(
            {
                "strategy": "offset",
                "size": {"default": pagination.get("defaultPageSize", min(20, maximum)), "max": maximum},
            },
            None,
            "api.pagination",
        )
