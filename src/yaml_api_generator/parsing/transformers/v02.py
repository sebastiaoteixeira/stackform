from typing import Any, cast

from ...ir import (
    IRAccessRule,
    IRApi,
    IRCollection,
    IRDocument,
    IRIdentityCollection,
    IROperations,
    IRRoute,
    IRService,
)
from ..parser import ConfigError, ConfigErrors

OPERATION_NAMES = ("list", "get", "create", "update", "replace", "delete")


def _normalize_operations(
    global_defaults: dict[str, Any], entity_ops: dict[str, Any] | None
) -> IROperations:
    defaults = {name: True for name in OPERATION_NAMES}
    for name in OPERATION_NAMES:
        if name in global_defaults:
            defaults[name] = bool(global_defaults[name])
    if entity_ops:
        for name in OPERATION_NAMES:
            if name in entity_ops:
                defaults[name] = bool(entity_ops[name])
    return IROperations(**defaults)


def _extract_entity_id_field(
    entity_name: str, fields: dict[str, Any]
) -> tuple[str | None, list[ConfigError]]:
    id_fields = [
        name
        for name, cfg in fields.items()
        if isinstance(cfg, dict) and cfg.get("type") == "id"
    ]
    if len(id_fields) == 1:
        return id_fields[0], []
    if not id_fields:
        return None, [
            ConfigError(
                code="ID_FIELD_MISSING",
                message="Entity must define exactly one field with type 'id'",
                path=f"entities.{entity_name}.fields",
            )
        ]
    return None, [
        ConfigError(
            code="ID_FIELD_MULTIPLE",
            message="Entity must define exactly one field with type 'id'",
            path=f"entities.{entity_name}.fields",
            hint=f"Found multiple id fields: {', '.join(id_fields)}",
        )
    ]


def _resolve_id_format(
    entity_name: str, id_field: str, fields: dict[str, Any]
) -> tuple[str | None, list[ConfigError]]:
    cfg = fields.get(id_field)
    if not isinstance(cfg, dict):
        return None, [
            ConfigError(
                code="ID_FIELD_INVALID",
                message="Entity id field configuration is invalid",
                path=f"entities.{entity_name}.fields.{id_field}",
            )
        ]
    raw = cfg.get("format")
    if raw is None:
        return "uuidv7", []
    if raw in {"uuidv7", "uuidv4"}:
        return str(raw), []
    return None, [
        ConfigError(
            code="ID_FORMAT_INVALID",
            message="id field format must be uuidv7 or uuidv4",
            path=f"entities.{entity_name}.fields.{id_field}.format",
        )
    ]


def _normalize_auth_via(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return cast(list[str], list(value))
    return []


def _resolve_imports(imports: dict[str, str]) -> dict[str, str]:
    return dict(imports)


def _resolve_handler_path(
    handler_ref: str, import_map: dict[str, str]
) -> str:
    parts = handler_ref.split(".", 1)
    alias = parts[0]
    module = import_map.get(alias)
    if module is None:
        return handler_ref
    if len(parts) == 2:
        return f"{module}.{parts[1]}"
    return module


def _parse_access_value(access: Any) -> tuple[bool, list[IRAccessRule] | None]:
    if access is None or access == "public":
        return True, None
    if access == "authenticated":
        return False, None
    if isinstance(access, str) and access.startswith("identity:"):
        return False, [IRAccessRule(principal=access)]
    if isinstance(access, list):
        rules = []
        for rule in access:
            if not isinstance(rule, dict):
                continue
            principal = rule.get("principal", "")
            rules.append(
                IRAccessRule(
                    principal=principal,
                    when=rule.get("when"),
                    filter=rule.get("filter"),
                    write_fields=rule.get("writeFields", []),
                    reason=rule.get("reason"),
                )
            )
        if rules:
            return False, rules
    return True, None


def _validate_implicit_auth_fields(
    collections: dict[str, IRCollection],
    identity_collections: dict[str, IRIdentityCollection],
) -> list[ConfigError]:
    errors: list[ConfigError] = []
    for name, identity in identity_collections.items():
        if "password" not in identity.via:
            continue
        fields = collections[name].fields
        if "password" in fields:
            errors.append(
                ConfigError(
                    code="AUTH_PASSWORD_FIELD_FORBIDDEN",
                    message="Password input is implicit when auth.via includes password",
                    path=f"entities.{name}.fields.password",
                    hint="Remove the password field from YAML",
                )
            )
        if "passwordHash" in fields:
            errors.append(
                ConfigError(
                    code="AUTH_PASSWORD_HASH_FIELD_FORBIDDEN",
                    message="passwordHash is implicit storage when auth.via includes password",
                    path=f"entities.{name}.fields.passwordHash",
                    hint="Remove the passwordHash field from YAML",
                )
            )
    return errors


class V02Transformer:
    def transform(self, resolved: dict[str, Any]) -> IRDocument:
        api_data: dict[str, Any] = resolved.get("api", {})
        defaults = api_data.get("operations", {}).get("defaults", {})
        import_map = _resolve_imports(resolved.get("imports", {}))
        entities_data: dict[str, Any] = resolved.get("entities", {})
        repos_data: dict[str, Any] = resolved.get("repositories", {})
        services_data: dict[str, Any] = resolved.get("services", {})
        controllers_data: dict[str, Any] = resolved.get("controllers", {})

        # repo name -> entity name
        repo_entity_map: dict[str, str] = {}
        for repo_name, repo_cfg in repos_data.items():
            if isinstance(repo_cfg, dict):
                repo_entity_map[repo_name] = repo_cfg["entity"]

        collections, id_errors = self._build_collections(entities_data, defaults)
        if id_errors:
            raise ConfigErrors(id_errors)

        identity_collections = self._build_identity_collections(
            entities_data, collections
        )

        field_errors = _validate_implicit_auth_fields(collections, identity_collections)
        if field_errors:
            raise ConfigErrors(field_errors)

        services = self._build_services(
            services_data, repo_entity_map, import_map
        )
        routes = self._build_routes(
            controllers_data, services, api_data, repo_entity_map
        )

        return IRDocument(
            version=str(resolved["version"]),
            api=IRApi(
                basePath=api_data.get("basePath", "/api"),
                version=api_data.get("version"),
            ),
            collections=collections,
            routes=routes,
            identityCollections=identity_collections,
            services=services,
        )

    def _build_collections(
        self,
        entities_data: dict[str, Any],
        defaults: dict[str, Any],
    ) -> tuple[dict[str, IRCollection], list[ConfigError]]:
        collections: dict[str, IRCollection] = {}
        errors: list[ConfigError] = []

        for name, entity_data in entities_data.items():
            entity_type = str(entity_data.get("type", "base"))
            operations = _normalize_operations(defaults, entity_data.get("operations"))
            fields = cast(dict[str, Any], entity_data["fields"])

            id_field, id_errors = _extract_entity_id_field(name, fields)
            errors.extend(id_errors)

            id_format: str | None = None
            if id_field is not None:
                id_format, fmt_errors = _resolve_id_format(name, id_field, fields)
                errors.extend(fmt_errors)

            if id_field is None or id_format is None:
                continue

            # v0.2 uses singular entity names; pluralize for collection name
            plural = name + "s"
            collections[plural] = IRCollection(
                name=plural,
                type=entity_type,
                idField=id_field,
                idFormat=id_format,
                fields=fields,
                operations=operations,
            )

        return collections, errors

    def _build_identity_collections(
        self,
        entities_data: dict[str, Any],
        collections: dict[str, IRCollection],
    ) -> dict[str, IRIdentityCollection]:
        identity_collections: dict[str, IRIdentityCollection] = {}
        for name, entity_data in entities_data.items():
            if str(entity_data.get("type", "base")) != "auth":
                continue
            plural = name + "s"
            if plural not in collections:
                continue
            auth_data = entity_data.get("auth", {})
            identifier = auth_data.get("identifier") if isinstance(auth_data, dict) else None
            via = _normalize_auth_via(auth_data.get("via") if isinstance(auth_data, dict) else None)
            identity_collections[plural] = IRIdentityCollection(
                name=plural,
                identifier=identifier,
                via=via,
            )
        return identity_collections

    def _build_services(
        self,
        services_data: dict[str, Any],
        repo_entity_map: dict[str, str],
        import_map: dict[str, str],
    ) -> dict[str, IRService]:
        services: dict[str, IRService] = {}
        for svc_name, svc_cfg in services_data.items():
            if not isinstance(svc_cfg, dict):
                continue

            handler_ref = svc_cfg.get("handler")
            repo_name = svc_cfg.get("repository")
            operation = svc_cfg.get("operation")

            if handler_ref is not None:
                resolved_handler = _resolve_handler_path(handler_ref, import_map)
                services[svc_name] = IRService(
                    name=svc_name,
                    handler=resolved_handler,
                )
            else:
                services[svc_name] = IRService(
                    name=svc_name,
                    repository=repo_name,
                    operation=operation,
                )
        return services

    def _build_routes(
        self,
        controllers_data: dict[str, Any],
        services: dict[str, IRService],
        api_data: dict[str, Any],
        repo_entity_map: dict[str, str],
    ) -> list[IRRoute]:
        base_path = api_data.get("basePath", "/api")
        routes: list[IRRoute] = []

        for _ctrl_name, ctrl_cfg in controllers_data.items():
            if not isinstance(ctrl_cfg, dict):
                continue
            ctrl_base = ctrl_cfg.get("base_path", "")
            ctrl_routes = ctrl_cfg.get("routes", {})

            for _route_name, route_cfg in ctrl_routes.items():
                if not isinstance(route_cfg, dict):
                    continue

                svc_name = route_cfg["service"]
                method = route_cfg["method"]
                path = route_cfg["path"]
                full_path = base_path + ctrl_base + path

                service = services.get(svc_name)
                is_public, access_rules = _parse_access_value(
                    route_cfg.get("access")
                )

                # Resolve collection from service -> repository -> entity
                collection: str | None = None
                handler: str | None = None
                operation: str | None = None

                if service is not None:
                    handler = service.handler
                    if service.repository is not None:
                        entity_name = repo_entity_map.get(service.repository, "")
                        collection = entity_name + "s" if entity_name else service.repository
                        operation = service.operation or svc_name
                    else:
                        operation = svc_name

                routes.append(
                    IRRoute(
                        method=method,
                        path=full_path,
                        operation=operation or svc_name,
                        collection=collection,
                        service=svc_name,
                        is_public=is_public,
                        access_rules=access_rules,
                        handler=handler,
                    )
                )

        return routes
