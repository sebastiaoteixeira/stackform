from typing import Any, cast

from ...ir import (
    IRAccessRule,
    IRApi,
    IRCollection,
    IRDocument,
    IRDocumentBinding,
    IRIdentityCollection,
    IROperations,
    IRRolesConfig,
    IRRoute,
    IRService,
)
from ..parser import ConfigError, ConfigErrors
from ..when_parser import parse_document_binding, parse_when_list

OPERATION_NAMES = ("list", "get", "create", "update", "replace", "delete")


def _normalize_operations(
    global_defaults: dict[str, Any], repo_ops: dict[str, Any] | None
) -> IROperations:
    defaults = {name: True for name in OPERATION_NAMES}
    for name in OPERATION_NAMES:
        if name in global_defaults:
            defaults[name] = bool(global_defaults[name])
    if repo_ops:
        for name in OPERATION_NAMES:
            if name in repo_ops:
                defaults[name] = bool(repo_ops[name])
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


def _parse_access_value(
    access: Any,
    path: str,
    auth_entities: set[str],
    entity_to_collection: dict[str, str],
) -> tuple[bool, list[IRAccessRule] | None, list[ConfigError]]:
    if access is None or access == "public":
        return True, None, []

    if access == "*":
        return False, None, []

    if access == "authenticated":
        return False, None, []

    if isinstance(access, str):
        rule, errors = _parse_access_string(access, path, auth_entities, entity_to_collection)
        if errors:
            return False, None, errors
        if rule is not None:
            return False, [rule], []
        return False, None, []

    if isinstance(access, list):
        rules: list[IRAccessRule] = []
        errors: list[ConfigError] = []
        for i, item in enumerate(access):
            item_path = f"{path}[{i}]"
            if isinstance(item, str):
                rule, str_errors = _parse_access_string(
                    item, item_path, auth_entities, entity_to_collection
                )
                errors.extend(str_errors)
                if rule is not None:
                    rules.append(rule)
            elif isinstance(item, dict):
                rule, dict_errors = _parse_access_rule_object(
                    item, item_path, auth_entities, entity_to_collection
                )
                errors.extend(dict_errors)
                if rule is not None:
                    rules.append(rule)
        if errors:
            return False, None, errors
        if rules:
            return False, rules, []
        return False, None, []

    return True, None, []


def _parse_access_string(
    value: str,
    path: str,
    auth_entities: set[str],
    entity_to_collection: dict[str, str],
) -> tuple[IRAccessRule | None, list[ConfigError]]:
    if value == "public":
        return None, []
    if value in ("*", "authenticated"):
        return None, []

    # identity:entity format (from rule objects)
    if value.startswith("identity:"):
        entity_name = value[len("identity:"):]
        collection = entity_to_collection.get(entity_name)
        if collection is None:
            return None, [
                ConfigError(
                    code="ACCESS_UNKNOWN_ENTITY",
                    message=f"Unknown auth entity '{entity_name}' in access rule",
                    path=path,
                )
            ]
        return IRAccessRule(principal=f"identity:{collection}"), []

    # entity:role or entity:* format
    if ":" in value:
        entity_part, role_part = value.split(":", 1)
        if entity_part not in auth_entities:
            return None, [
                ConfigError(
                    code="ACCESS_UNKNOWN_ENTITY",
                    message=f"Unknown auth entity '{entity_part}' in access rule",
                    path=path,
                )
            ]
        collection = entity_to_collection[entity_part]
        if role_part == "*":
            return IRAccessRule(principal=f"identity:{collection}"), []
        return IRAccessRule(
            principal=f"identity:{collection}", required_role=role_part
        ), []

    # Unscoped role — only valid with single auth entity
    if len(auth_entities) == 0:
        return None, [
            ConfigError(
                code="ACCESS_NO_AUTH_ENTITY",
                message=f"Cannot use role '{value}' without auth entities",
                path=path,
            )
        ]
    if len(auth_entities) > 1:
        return None, [
            ConfigError(
                code="ACCESS_AMBIGUOUS_ROLE",
                message=f"Unscoped role '{value}' is ambiguous with multiple auth entities; use 'entity:{value}'",
                path=path,
            )
        ]
    entity_name = next(iter(auth_entities))
    collection = entity_to_collection[entity_name]
    return IRAccessRule(
        principal=f"identity:{collection}", required_role=value
    ), []


def _parse_access_rule_object(
    rule: dict[str, Any],
    path: str,
    auth_entities: set[str],
    entity_to_collection: dict[str, str],
) -> tuple[IRAccessRule | None, list[ConfigError]]:
    errors: list[ConfigError] = []

    given = rule.get("given", {})
    principal_raw = given.get("principal", "") if isinstance(given, dict) else ""
    effect = rule.get("then", "allow")

    # Resolve principal
    principal = ""
    required_role: str | None = None
    if principal_raw.startswith("identity:"):
        entity_name = principal_raw[len("identity:"):]
        collection = entity_to_collection.get(entity_name)
        if collection is None:
            errors.append(
                ConfigError(
                    code="ACCESS_UNKNOWN_ENTITY",
                    message=f"Unknown auth entity '{entity_name}' in access rule",
                    path=f"{path}.given.principal",
                )
            )
        else:
            principal = f"identity:{collection}"
    else:
        principal = principal_raw

    doc_binding: IRDocumentBinding | None = None
    doc_raw = given.get("document") if isinstance(given, dict) else None
    if doc_raw is not None:
        parsed, doc_errors = parse_document_binding(
            doc_raw, f"{path}.given.document"
        )
        errors.extend(doc_errors)
        if parsed is not None:
            doc_binding = IRDocumentBinding(
                collection=parsed[0], id_param=parsed[1]
            )

    when_expr = None
    when_raw = rule.get("when")
    if when_raw is not None:
        when_expr, when_errors = parse_when_list(
            when_raw, f"{path}.when"
        )
        errors.extend(when_errors)

    if errors:
        return None, errors

    return IRAccessRule(
        principal=principal,
        required_role=required_role,
        when=when_expr,
        document=doc_binding,
        effect=effect,
        filter=rule.get("filter"),
        write_fields=rule.get("writeFields", []),
        reason=rule.get("reason"),
    ), []


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


def _parse_roles_config(
    entity_name: str,
    raw: dict[str, Any],
) -> tuple[IRRolesConfig | None, list[ConfigError]]:
    errors: list[ConfigError] = []
    values = tuple(str(v) for v in raw.get("values", []))
    default = str(raw.get("default", ""))
    hierarchy_raw = raw.get("hierarchy", {})

    if default not in values:
        errors.append(ConfigError(
            code="ROLES_DEFAULT_NOT_IN_VALUES",
            message=f"roles.default '{default}' is not in roles.values",
            path=f"entities.{entity_name}.roles.default",
        ))

    hierarchy: dict[str, tuple[str, ...]] = {}
    if isinstance(hierarchy_raw, dict):
        for role, includes in hierarchy_raw.items():
            if role not in values:
                errors.append(ConfigError(
                    code="ROLES_HIERARCHY_KEY_INVALID",
                    message=f"Hierarchy role '{role}' is not in roles.values",
                    path=f"entities.{entity_name}.roles.hierarchy",
                ))
            bad = [r for r in (includes or []) if r not in values]
            for b in bad:
                errors.append(ConfigError(
                    code="ROLES_HIERARCHY_VALUE_INVALID",
                    message=f"Hierarchy includes role '{b}' which is not in roles.values",
                    path=f"entities.{entity_name}.roles.hierarchy.{role}",
                ))
            hierarchy[role] = tuple(str(r) for r in (includes or []))

    if errors:
        return None, errors
    return IRRolesConfig(values=values, default=default, hierarchy=hierarchy), []


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

        # entity name -> collection name (pluralized)
        entity_to_collection: dict[str, str] = {}
        for entity_name in entities_data:
            entity_to_collection[entity_name] = entity_name + "s"

        # Identify auth entities
        auth_entities: set[str] = set()
        for entity_name, entity_data in entities_data.items():
            if isinstance(entity_data, dict) and entity_data.get("type") == "auth":
                auth_entities.add(entity_name)

        collections, id_errors = self._build_collections(
            entities_data, repos_data, defaults
        )
        if id_errors:
            raise ConfigErrors(id_errors)

        identity_collections, identity_errors = self._build_identity_collections(
            entities_data, collections
        )
        if identity_errors:
            raise ConfigErrors(identity_errors)

        field_errors = _validate_implicit_auth_fields(collections, identity_collections)
        if field_errors:
            raise ConfigErrors(field_errors)

        services = self._build_services(
            services_data, repo_entity_map, import_map
        )
        routes = self._build_routes(
            controllers_data, services, api_data, repo_entity_map,
            auth_entities, entity_to_collection,
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
        repos_data: dict[str, Any],
        defaults: dict[str, Any],
    ) -> tuple[dict[str, IRCollection], list[ConfigError]]:
        collections: dict[str, IRCollection] = {}
        errors: list[ConfigError] = []

        # Build repo_name -> repo_cfg mapping for operation lookup
        entity_repo_map: dict[str, dict[str, Any]] = {}
        for repo_name, repo_cfg in repos_data.items():
            if isinstance(repo_cfg, dict) and "entity" in repo_cfg:
                entity_repo_map[repo_cfg["entity"]] = repo_cfg

        for name, entity_data in entities_data.items():
            entity_type = str(entity_data.get("type", "base"))
            fields = cast(dict[str, Any], entity_data.get("fields", {}))

            # Operations from repository, not entity
            repo_cfg = entity_repo_map.get(name, {})
            repo_ops = repo_cfg.get("operations") if isinstance(repo_cfg, dict) else None
            operations = _normalize_operations(defaults, repo_ops)

            pk_field = entity_data.get("pk")
            if pk_field is not None:
                # Natural key — use pk field as idField
                if pk_field not in fields:
                    errors.append(
                        ConfigError(
                            code="PK_FIELD_NOT_FOUND",
                            message=f"pk field '{pk_field}' not found in entity '{name}'",
                            path=f"entities.{name}.pk",
                        )
                    )
                    continue
                id_field = pk_field
                id_format = "natural"
            else:
                id_field_result, id_errors = _extract_entity_id_field(name, fields)
                errors.extend(id_errors)

                id_format_result: str | None = None
                if id_field_result is not None:
                    id_format_result, fmt_errors = _resolve_id_format(name, id_field_result, fields)
                    errors.extend(fmt_errors)

                if id_field_result is None or id_format_result is None:
                    continue

                id_field = id_field_result
                id_format = id_format_result

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
    ) -> tuple[dict[str, IRIdentityCollection], list[ConfigError]]:
        identity_collections: dict[str, IRIdentityCollection] = {}
        errors: list[ConfigError] = []

        for name, entity_data in entities_data.items():
            if str(entity_data.get("type", "base")) != "auth":
                roles_raw = entity_data.get("roles")
                if roles_raw is not None:
                    errors.append(ConfigError(
                        code="ROLES_ON_NON_AUTH_ENTITY",
                        message="roles: section is only valid on type: auth entities",
                        path=f"entities.{name}.roles",
                    ))
                continue
            plural = name + "s"
            if plural not in collections:
                continue
            auth_data = entity_data.get("auth", {})
            identifier = auth_data.get("identifier") if isinstance(auth_data, dict) else None
            via = _normalize_auth_via(auth_data.get("via") if isinstance(auth_data, dict) else None)

            roles_config: IRRolesConfig | None = None
            roles_raw = entity_data.get("roles")
            if isinstance(roles_raw, dict):
                parsed_roles, role_errors = _parse_roles_config(name, roles_raw)
                errors.extend(role_errors)
                if parsed_roles is not None:
                    roles_config = parsed_roles

            identity_collections[plural] = IRIdentityCollection(
                name=plural,
                identifier=identifier,
                via=via,
                roles=roles_config,
            )

        return identity_collections, errors

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
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> list[IRRoute]:
        base_path = api_data.get("basePath", "/api")
        routes: list[IRRoute] = []
        all_errors: list[ConfigError] = []

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
                access_path = f"controllers.{_ctrl_name}.routes.{_route_name}.access"
                is_public, access_rules, access_errors = _parse_access_value(
                    route_cfg.get("access"), access_path,
                    auth_entities, entity_to_collection,
                )
                all_errors.extend(access_errors)

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

        if all_errors:
            raise ConfigErrors(all_errors)

        return routes
