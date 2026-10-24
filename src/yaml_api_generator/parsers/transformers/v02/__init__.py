"""V0.2 YAML to IR transformation orchestrator.

Coordinates specialized transformers to convert v0.2 YAML specifications into IR objects.
"""

from dataclasses import fields as dataclass_fields
from operator import attrgetter
from typing import Any

from yaml_api_generator.ir import IRDocument
from yaml_api_generator.ir.api import IROIDCProvider, IRProvider, IRSAMLProvider, IRSession
from yaml_api_generator.parsers.yaml_parser import ConfigErrors

from .access_transformer import AccessTransformer
from .collection_transformer import CollectionTransformer
from .datastore_transformer import parse_datastores, parse_file_datastores
from .dto_transformer import DtoTransformer
from .file_transformer import FileStoreRegistry, FileTransformer
from .identity_transformer import IdentityTransformer
from .policies_transformer import PoliciesTransformer
from .policy_expansion import expand_rule_policies
from .repository_transformer import RepositoryTransformer
from .route_transformer import RouteTransformer


class V02Transformer:
    """Orchestrates v0.2 YAML to IR transformation."""

    def __init__(self):
        self._repository = RepositoryTransformer()
        self._collection = CollectionTransformer()
        self._dto = DtoTransformer()
        self._identity = IdentityTransformer()
        self._access = AccessTransformer()
        self._route = RouteTransformer(self._access)
        self._policies = PoliciesTransformer()
        self._files = FileTransformer()

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
        import_map, vendored_imports, vendored_requirements = self._process_imports(resolved)
        entities_data: dict[str, Any] = resolved.get("entities", {})
        repos_data: dict[str, Any] = resolved.get("repositories", {})
        services_data: dict[str, Any] = resolved.get("services", {})
        controllers_data: dict[str, Any] = resolved.get("controllers", {})
        providers_data: dict[str, Any] = resolved.get("providers", {})
        dtos_data: dict[str, Any] = resolved.get("dto", {})
        policies_data: dict[str, Any] = resolved.get("policies", {})

        datastores, default_datastore, datastore_errors = parse_datastores(resolved)
        file_stores, default_file_store, file_store_errors = parse_file_datastores(resolved)
        if datastore_errors or file_store_errors:
            raise ConfigErrors(datastore_errors + file_store_errors)
        datastore_names = set(datastores)
        datastore_types = {name: ds.type for name, ds in datastores.items()}

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
            entities_data, repos_data, defaults, datastore_names, default_datastore
        )
        if id_errors:
            raise ConfigErrors(id_errors)

        repositories, repo_errors = self._repository.transform(
            repos_data, defaults, datastore_names, default_datastore, datastore_types,
            handler_resolver=self._operation_handler_resolver(import_map),
            file_datastore_names=set(file_stores),
        )
        if repo_errors:
            raise ConfigErrors(repo_errors)

        collections, repositories, binding_errors = self._files.bind(
            resolved, collections, repositories,
            FileStoreRegistry.from_spec(resolved, file_stores, default_file_store, datastore_names),
        )
        if binding_errors:
            raise ConfigErrors(binding_errors)

        identity_collections = self._identity.transform(
            entities_data, collections, repo_entity_map
        )

        field_errors = self._identity.validate_auth_fields(collections, identity_collections)
        if field_errors:
            raise ConfigErrors(field_errors)

        services = self._route.transform_services(
            services_data, repo_entity_map, import_map, dtos_data
        )
        routes = self._route.transform_routes(
            controllers_data,
            services,
            repositories,
            api_data,
            repo_entity_map,
            auth_entities,
            entity_to_collection,
            pagination_parser=self._make_pagination_parser(collections),
        )

        policies, policy_errors = self._policies.transform(
            policies_data, entity_to_collection
        )
        if policy_errors:
            raise ConfigErrors(policy_errors)

        routes = self._expand_route_policies(routes, policies, entity_to_collection)
        file_routes, file_route_errors = self._files.derive(collections, routes)
        if file_route_errors:
            raise ConfigErrors(file_route_errors)

        providers = self._parse_providers(providers_data)

        dtos, dto_errors = self._dto.transform(dtos_data)
        if dto_errors:
            raise ConfigErrors(dto_errors)

        mongo_config = resolved.get("mongo", {})
        return IRDocument(
            version=str(resolved["version"]),
            api=self._route.build_api(api_data),
            collections=collections,
            routes=sorted(routes, key=attrgetter("precedence")),
            identityCollections=identity_collections,
            dtos=dtos,
            services=services,
            service_bases=self._route.transform_service_bases(services_data, import_map),
            mongo=self._route.build_mongo(mongo_config),
            datastores=datastores,
            default_datastore=default_datastore,
            file_stores=file_stores,
            default_file_store=default_file_store,
            file_routes=file_routes,
            deploy=self._route.build_deploy(resolved.get("deploy"), mongo_config, providers, datastores),
            repositories=repositories,
            providers=providers,
            policies=policies,
            session=self._build_session(resolved.get("session", {})),
            ui_config=resolved.get("ui"),
            vendored_imports=vendored_imports,
            vendored_requirements=vendored_requirements,
        )

    @staticmethod
    def _build_session(session_data: dict[str, Any]) -> IRSession:
        return IRSession(
            algorithm=session_data.get("algorithm", "HS256"),
            ttl=session_data.get("ttl"),
            refresh=session_data.get("refresh", False),
            delivery=session_data.get("delivery", "token-url"),
        )

    def _process_imports(
        self, resolved: dict[str, Any]
    ) -> tuple[dict[str, str], tuple[Any, ...], tuple[str, ...]]:
        return self._route._resolve_imports(resolved.get("imports", {})), (), ()

    def _operation_handler_resolver(self, import_map: dict[str, str]):
        return lambda handler: handler

    def _make_pagination_parser(self, collections: dict[str, Any]):
        return lambda raw, collection, path: (None, [])

    def _expand_route_policies(
        self,
        routes: list[Any],
        policies: dict[str, Any],
        entity_to_collection: dict[str, str],
    ) -> list[Any]:
        from dataclasses import replace

        errors = []
        expanded_routes = []
        for route in routes:
            if not route.access_rules:
                expanded_routes.append(route)
                continue
            new_rules = []
            for index, rule in enumerate(route.access_rules):
                expanded, rule_errors = expand_rule_policies(
                    rule, policies, entity_to_collection,
                    f"{route.method} {route.path} access[{index}]",
                )
                errors.extend(rule_errors)
                new_rules.append(expanded)
            expanded_routes.append(replace(route, access_rules=new_rules))
        if errors:
            raise ConfigErrors(errors)
        return expanded_routes

    def _parse_providers(self, providers_data: dict[str, Any]) -> dict[str, IRProvider]:
        _CONSTRUCTORS: dict[str, type] = {"oidc": IROIDCProvider, "saml": IRSAMLProvider}
        providers: dict[str, IRProvider] = {}
        for name, cfg in providers_data.items():
            if not isinstance(cfg, dict):
                continue
            ctor = _CONSTRUCTORS.get(cfg.get("type"))
            if ctor is None:
                continue
            accepted = {f.name for f in dataclass_fields(ctor)} - {"name"}
            kwargs = {k: v for k, v in cfg.items() if k in accepted}
            if ctor is IROIDCProvider and "audiences" in kwargs:
                kwargs["audiences"] = tuple(kwargs["audiences"])
            providers[name] = ctor(name=name, **kwargs)
        return providers
