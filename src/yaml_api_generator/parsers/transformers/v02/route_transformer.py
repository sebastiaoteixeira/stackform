"""Route, service, and config transformation to IR.

Builds routes from controllers, services, API, MongoDB, and deploy configurations.
"""

from typing import Any

from yaml_api_generator.ir import (
    IRApi,
    IRCors,
    IRDeploy,
    IRDeployDocker,
    IRDeploySystemd,
    IRMongo,
    IRRoute,
    IRService,
)
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors

from .access_transformer import AccessTransformer


class RouteTransformer:
    """Builds routes from controllers and services."""

    def __init__(self, access_transformer: AccessTransformer):
        self._access_transformer = access_transformer

    def transform_services(
        self,
        services_data: dict[str, Any],
        repo_entity_map: dict[str, str],
        import_map: dict[str, str],
    ) -> dict[str, IRService]:
        """Transform service configurations to IR.

        Args:
            services_data: Raw service configurations from YAML
            repo_entity_map: Repository name to entity name mapping
            import_map: Handler import path resolution

        Returns:
            Dictionary of service IR objects
        """
        services: dict[str, IRService] = {}
        for svc_name, svc_cfg in services_data.items():
            if not isinstance(svc_cfg, dict):
                continue
            handler_ref = svc_cfg.get("handler")
            if handler_ref is not None:
                services[svc_name] = IRService(
                    name=svc_name,
                    handler=self._resolve_handler_path(handler_ref, import_map),
                )
            else:
                services[svc_name] = IRService(
                    name=svc_name,
                    repository=svc_cfg.get("repository"),
                    operation=svc_cfg.get("operation"),
                )
        return services

    def transform_routes(
        self,
        controllers_data: dict[str, Any],
        services: dict[str, IRService],
        api_data: dict[str, Any],
        repo_entity_map: dict[str, str],
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
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
                service = services.get(svc_name)

                is_public, access_rules, access_errors = self._access_transformer.parse_access(
                    route_cfg.get("access"),
                    f"controllers.{ctrl_name}.routes.{route_name}.access",
                    auth_entities,
                    entity_to_collection,
                )
                all_errors.extend(access_errors)

                collection: str | None = None
                handler: str | None = None
                operation: str | None = None
                if service is not None:
                    handler = service.handler
                    if service.repository is not None:
                        collection = service.repository
                        operation = service.operation or route_name
                    else:
                        operation = route_name

                routes.append(
                    IRRoute(
                        method=route_cfg["method"],
                        path=full_path,
                        operation=operation or route_name,
                        collection=collection,
                        service=svc_name,
                        is_public=is_public,
                        access_rules=access_rules,
                        handler=handler,
                    )
                )

        if all_errors:
            raise ConfigErrors(all_errors)

        return routes

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

    def build_deploy(self, deploy_data: Any, full_config: dict[str, Any], mongo_config: dict[str, Any]) -> IRDeploy | None:
        """Build deployment configuration IR.

        Args:
            deploy_data: Raw deployment configuration from YAML
            full_config: Full YAML configuration for extracting env vars
            mongo_config: MongoDB configuration to determine if local

        Returns:
            Deploy IR object or None if no deployment configured
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

        env_vars = self._extract_env_vars(full_config)

        return IRDeploy(
            runtime=str(runtime),
            name=deploy_data.get("name"),
            port=int(deploy_data.get("port", 8000)),
            mongo_local=mongo_local,
            env_vars=tuple(env_vars),
            docker=docker,
            systemd=systemd,
        )

    def _extract_env_vars(self, config: dict[str, Any]) -> list[str]:
        """Extract environment variable names from config values.

        Looks for ${VAR_NAME} or ${VAR_NAME:-default} patterns.
        """
        import re
        env_var_pattern = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)(?::-[^}]*)?\}')

        def find_env_vars(obj: Any, vars_set: set[str]) -> None:
            if isinstance(obj, str):
                vars_set.update(env_var_pattern.findall(obj))
            elif isinstance(obj, dict):
                for value in obj.values():
                    find_env_vars(value, vars_set)
            elif isinstance(obj, list):
                for item in obj:
                    find_env_vars(item, vars_set)

        vars_set: set[str] = set()
        find_env_vars(config, vars_set)
        return sorted(vars_set)

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
