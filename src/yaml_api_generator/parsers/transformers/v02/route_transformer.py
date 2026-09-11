"""Route, service, and config transformation to IR.

Builds routes from controllers, services, API, MongoDB, and deploy configurations.
"""

from typing import Any

from yaml_api_generator.ir import (
    IRApi,
    IRCors,
    IRDatastore,
    IRDeploy,
    IRDeployDocker,
    IRDeploySystemd,
    IRMongo,
    IRProvider,
    IRRoute,
    IRService,
)
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors

from .access_transformer import AccessTransformer


class RouteTransformer:
    """Builds routes from controllers and services."""

    def __init__(
        self,
        access_transformer: AccessTransformer,
        allow_service_inputs: bool = False,
    ):
        self._access_transformer = access_transformer
        self._allow_service_inputs = allow_service_inputs

    def transform_services(
        self,
        services_data: dict[str, Any],
        repo_entity_map: dict[str, str],
        import_map: dict[str, str],
        dtos_data: dict[str, Any] | None = None,
    ) -> dict[str, IRService]:
        """Transform service configurations to IR.

        Args:
            services_data: Raw service configurations from YAML
            repo_entity_map: Repository name to entity name mapping
            import_map: Handler import path resolution
            dtos_data: Raw DTO definitions, resolved by service ``input:`` refs

        Returns:
            Dictionary of service IR objects

        Raises:
            ConfigErrors: If a service ``input:`` / ``with:`` is malformed
        """
        dtos_data = dtos_data or {}
        services: dict[str, IRService] = {}
        errors: list[ConfigError] = []
        for svc_name, svc_cfg in services_data.items():
            if not isinstance(svc_cfg, dict):
                continue
            input_ir, forwarding = self._transform_input(svc_name, svc_cfg, dtos_data, errors)
            handler_ref = svc_cfg.get("handler")
            inherits = svc_cfg.get("_inherits")
            if handler_ref is not None:
                services[svc_name] = IRService(
                    name=svc_name,
                    handler=self._resolve_handler_path(handler_ref, import_map),
                    inherits=inherits,
                    input=input_ir,
                    forwarding=forwarding,
                )
            else:
                services[svc_name] = IRService(
                    name=svc_name,
                    repository=svc_cfg.get("repository"),
                    operation=svc_cfg.get("operation"),
                    inherits=inherits,
                    input=input_ir,
                    forwarding=forwarding,
                )
        if errors:
            raise ConfigErrors(errors)
        return services

    def _transform_input(
        self,
        svc_name: str,
        svc_cfg: dict[str, Any],
        dtos_data: dict[str, Any],
        errors: list[ConfigError],
    ) -> tuple[Any, dict[str, Any]]:
        from yaml_api_generator.parsers.service_input_parser import (
            parse_service_input,
            parse_service_with,
        )

        input_ir = None
        if not self._allow_service_inputs and ({"input", "with"} & svc_cfg.keys()):
            errors.append(
                ConfigError(
                    code="SERVICE_INPUT_UNSUPPORTED",
                    message="service input and with forwarding require spec version 0.3",
                    path=f"services.{svc_name}",
                    hint='Set version to "0.3"',
                )
            )
            return None, {}
        if "input" in svc_cfg:
            input_ir, input_errors = parse_service_input(
                svc_cfg["input"], dtos_data, f"services.{svc_name}.input"
            )
            errors.extend(input_errors)

        forwarding: dict[str, Any] = {}
        if isinstance(svc_cfg.get("with"), dict):
            forwarding, with_errors = parse_service_with(
                svc_cfg["with"], f"services.{svc_name}.with"
            )
            errors.extend(with_errors)
        return input_ir, forwarding

    def transform_routes(
        self,
        controllers_data: dict[str, Any],
        services: dict[str, IRService],
        api_data: dict[str, Any],
        repo_entity_map: dict[str, str],
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
        pagination_parser=None,
    ) -> list[IRRoute]:
        """Transform controller routes to IR.

        Args:
            controllers_data: Raw controller configurations from YAML
            services: Already-built service IR objects
            api_data: API configuration data
            repo_entity_map: Repository name to entity name mapping
            auth_entities: Set of entity names marked as auth type
            entity_to_collection: Entity name to collection name mapping

        Returns:
            List of route IR objects

        Raises:
            ConfigErrors: If access rule parsing fails
        """
        base_path = api_data.get("basePath", "/api")
        version = api_data.get("version", "")
        if version:
            base_path = f"{base_path}/{version}"

        routes: list[IRRoute] = []
        all_errors: list[ConfigError] = []

        for ctrl_name, ctrl_cfg in controllers_data.items():
            if not isinstance(ctrl_cfg, dict):
                continue
            ctrl_base = ctrl_cfg.get("base_path", "")
            ctrl_routes = ctrl_cfg.get("routes", {})

            for route_name, route_cfg in ctrl_routes.items():
                if not isinstance(route_cfg, dict):
                    continue

                svc_name = route_cfg["service"]
                full_path = base_path + ctrl_base + route_cfg["path"]
                service = self._resolve_service(svc_name, route_name, services)
                if service is None:
                    all_errors.append(
                        ConfigError(
                            code="DESUGAR_SERVICE_NOT_FOUND",
                            message=f"Service '{svc_name}' referenced by route is not defined",
                            path=f"controllers.{ctrl_name}.routes.{route_name}.service",
                        )
                    )
                    continue

                is_public, access_rules, access_errors = self._access_transformer.parse_access(
                    route_cfg.get("access"),
                    f"controllers.{ctrl_name}.routes.{route_name}.access",
                    auth_entities,
                    entity_to_collection,
                )
                all_errors.extend(access_errors)

                handler = service.handler
                collection = service.repository
                operation = service.operation or route_name

                pagination = None
                if pagination_parser is not None:
                    pagination, pagination_errors = pagination_parser(
                        route_cfg.get("pagination"),
                        collection,
                        f"controllers.{ctrl_name}.operations.{operation}.pagination",
                    )
                    all_errors.extend(pagination_errors)

                routes.append(
                    IRRoute(
                        method=route_cfg["method"],
                        path=full_path,
                        operation=operation,
                        collection=collection,
                        service=svc_name,
                        is_public=is_public,
                        access_rules=access_rules,
                        handler=handler,
                        pagination=pagination,
                    )
                )

        if all_errors:
            raise ConfigErrors(all_errors)

        return routes

    def _resolve_service(
        self, svc_name: str, route_name: str, services: dict[str, IRService]
    ) -> IRService | None:
        """Resolve a route's service reference to its IRService.

        Handles both the minified controller form (where the reference is an
        already-expanded flat key like 'list-posts') and the explicit routes
        form (where the reference is the service group 'posts' and the route
        name is the operation). For the explicit form, CRUD operations resolve
        to their flat key while custom operations inherit the group's
        repository so the route is bound to a collection.
        """
        direct = services.get(svc_name)
        if direct is not None:
            return direct

        flat_key = f"{route_name}-{svc_name}"
        crud = services.get(flat_key)
        if crud is not None:
            return crud

        repository = self._group_repository(svc_name, services)
        if repository is None:
            return None
        return IRService(
            name=flat_key, repository=repository, operation=route_name
        )

    def _group_repository(
        self, svc_name: str, services: dict[str, IRService]
    ) -> str | None:
        """Find the repository backing an expanded service group."""
        suffix = f"-{svc_name}"
        for key, service in services.items():
            if key.endswith(suffix) and service.repository is not None:
                return service.repository
        return None

    def build_api(self, api_data: dict[str, Any]) -> IRApi:
        """Build API configuration IR.

        Args:
            api_data: Raw API configuration from YAML

        Returns:
            API IR object
        """
        cors_raw = api_data.get("cors")
        cors = None
        if isinstance(cors_raw, dict):
            cors = IRCors(
                origins=cors_raw.get("origins", ["*"]),
                methods=cors_raw.get("methods", ["*"]),
                headers=cors_raw.get("headers", ["*"]),
                credentials=cors_raw.get("credentials", False),
            )
        return IRApi(
            basePath=api_data.get("basePath", "/api"),
            version=api_data.get("version"),
            cors=cors,
            port=int(api_data.get("port", 8000)),
        )

    def build_mongo(self, mongo_data: dict[str, Any]) -> IRMongo:
        """Build MongoDB configuration IR.

        Args:
            mongo_data: Raw MongoDB configuration from YAML

        Returns:
            MongoDB IR object
        """
        return IRMongo(
            uri=mongo_data.get("uri", "mongodb://localhost:27017"),
            database=mongo_data.get("database", "yaml_api"),
        )

    def build_deploy(
        self,
        deploy_data: Any,
        mongo_config: dict[str, Any],
        providers: dict[str, IRProvider],
        datastores: dict[str, IRDatastore],
    ) -> IRDeploy | None:
        """Build deployment configuration IR.

        Args:
            deploy_data: Raw deployment configuration from YAML.
            mongo_config: MongoDB configuration to determine if local.
            providers: Already-built provider IR objects (env vars resolved at build time).
            datastores: Already-built datastore IR objects (env vars resolved at build time).

        Returns:
            Deploy IR object or None if no deployment configured.
        """
        if not isinstance(deploy_data, dict):
            return None
        runtime = deploy_data.get("runtime")
        if not runtime:
            return None

        docker_data = deploy_data.get("docker")
        docker = IRDeployDocker(image=docker_data.get("image")) if isinstance(docker_data, dict) else None
        systemd_data = deploy_data.get("systemd")
        systemd = (
            IRDeploySystemd(
                user=systemd_data.get("user", "ubuntu"),
                restart=systemd_data.get("restart", "on-failure"),
            )
            if isinstance(systemd_data, dict)
            else None
        )

        mongo_uri = mongo_config.get("uri", "mongodb://localhost:27017")
        mongo_local = not mongo_config or "localhost" in mongo_uri or "127.0.0.1" in mongo_uri

        env_vars = self._collect_env_vars(deploy_data, providers, datastores)

        extra_services = tuple(
            (name, config) for name, config in deploy_data.get("services", {}).items()
        )
        include = tuple(deploy_data.get("include", []))

        return IRDeploy(
            runtime=str(runtime),
            name=deploy_data.get("name"),
            port=int(deploy_data.get("port", 8000)),
            mongo_local=mongo_local,
            env_vars=tuple(env_vars),
            docker=docker,
            systemd=systemd,
            extra_services=extra_services,
            include=include,
        )

    def _collect_env_vars(
        self,
        deploy_data: dict[str, Any],
        providers: dict[str, IRProvider],
        datastores: dict[str, IRDatastore],
    ) -> list[str]:
        """Collect env var names for the .env.example from the deploy subtree."""
        return sorted(self._scan_deploy_token_refs(deploy_data))

    def _scan_deploy_token_refs(self, deploy_data: dict[str, Any]) -> set[str]:
        """Scan raw deploy config strings for leftover ${VAR} tokens."""
        import re
        pattern = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)(?::-[^}]*)?\}')

        def _walk(obj: Any, result: set[str]) -> None:
            if isinstance(obj, str):
                result.update(pattern.findall(obj))
            elif isinstance(obj, dict):
                for v in obj.values():
                    _walk(v, result)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item, result)

        refs: set[str] = set()
        _walk(deploy_data, refs)
        return refs

    def _resolve_imports(self, imports: dict[str, str]) -> dict[str, str]:
        return dict(imports)

    def _resolve_handler_path(self, handler_ref: str, import_map: dict[str, str]) -> str:
        parts = handler_ref.split(".", 1)
        alias = parts[0]
        module = import_map.get(alias)
        if module is None:
            return handler_ref
        if len(parts) == 2:
            return f"{module}.{parts[1]}"
        return module
