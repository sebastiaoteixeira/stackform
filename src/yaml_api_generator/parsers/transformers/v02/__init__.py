"""V0.2 YAML to IR transformation orchestrator.

Coordinates specialized transformers to convert v0.2 YAML specifications into IR objects.
"""

from typing import Any

from yaml_api_generator.ir import IRDocument
from yaml_api_generator.parsers.yaml_parser import ConfigErrors

from .access_transformer import AccessTransformer
from .collection_transformer import CollectionTransformer
from .identity_transformer import IdentityTransformer
from .repository_transformer import RepositoryTransformer
from .route_transformer import RouteTransformer


class V02Transformer:
    """Orchestrates v0.2 YAML to IR transformation."""

    def __init__(self):
        self._repository = RepositoryTransformer()
        self._collection = CollectionTransformer()
        self._identity = IdentityTransformer()
        self._access = AccessTransformer()
        self._route = RouteTransformer(self._access)

    def transform(self, resolved: dict[str, Any]) -> IRDocument:
        """Transform v0.2 YAML specification to IR.

        Args:
            resolved: Fully resolved YAML specification dictionary

        Returns:
            Complete IRDocument with all components

        Raises:
            ConfigErrors: If any validation errors occur during transformation
        """
        api_data: dict[str, Any] = resolved.get("api", {})
        defaults = api_data.get("operations", {}).get("defaults", {})
        import_map = self._route._resolve_imports(resolved.get("imports", {}))
        entities_data: dict[str, Any] = resolved.get("entities", {})
        repos_data: dict[str, Any] = resolved.get("repositories", {})
        services_data: dict[str, Any] = resolved.get("services", {})
        controllers_data: dict[str, Any] = resolved.get("controllers", {})
        roles_data: dict[str, Any] = resolved.get("roles", {})

        repo_entity_map: dict[str, str] = {
            repo_name: repo_cfg["entity"]
            for repo_name, repo_cfg in repos_data.items()
            if isinstance(repo_cfg, dict) and "entity" in repo_cfg
        }
        entity_to_collection: dict[str, str] = {v: k for k, v in repo_entity_map.items()}

        auth_entities: set[str] = {
            name
            for name, data in entities_data.items()
            if isinstance(data, dict) and data.get("type") == "auth"
        }

        collections, id_errors = self._collection.transform(
            entities_data, repos_data, defaults
        )
        if id_errors:
            raise ConfigErrors(id_errors)

        repositories, repo_errors = self._repository.transform(repos_data, defaults)
        if repo_errors:
            raise ConfigErrors(repo_errors)

        identity_collections = self._identity.transform(
            entities_data, collections, repo_entity_map
        )

        field_errors = self._identity.validate_auth_fields(collections, identity_collections)
        if field_errors:
            raise ConfigErrors(field_errors)

        role_hierarchies: dict[str, dict[str, list[str]]] = {}
        if roles_data:
            role_hierarchies, role_errors = self._identity.parse_role_hierarchies(
                roles_data, auth_entities
            )
            if role_errors:
                raise ConfigErrors(role_errors)

        services = self._route.transform_services(services_data, repo_entity_map, import_map)
        routes = self._route.transform_routes(
            controllers_data,
            services,
            api_data,
            repo_entity_map,
            auth_entities,
            entity_to_collection,
        )

        mongo_config = resolved.get("mongo", {})
        return IRDocument(
            version=str(resolved["version"]),
            api=self._route.build_api(api_data),
            collections=collections,
            routes=routes,
            identityCollections=identity_collections,
            services=services,
            role_hierarchies=role_hierarchies,
            mongo=self._route.build_mongo(mongo_config),
            deploy=self._route.build_deploy(resolved.get("deploy"), resolved, mongo_config),
            repositories=repositories,
            ui_config=resolved.get("ui"),
        )
