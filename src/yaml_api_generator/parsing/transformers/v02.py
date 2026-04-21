from typing import Any, cast

from ...ir import (
    IRAccessRule,
    IRApi,
    IRCollection,
    IRDocument,
    IRDocumentBinding,
    IRIdentityCollection,
    IROIDCProvider,
    IRProvider,
    IRProviderBinding,
    IRSAMLProvider,
    IROperations,
    IRRoute,
    IRService,
    WELL_KNOWN_OIDC_DISCOVERY,
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
        if not identity.has_password:
            continue
        fields = collections[name].fields
        if "password" in fields:
            errors.append(
                ConfigError(
                    code="AUTH_PASSWORD_FIELD_FORBIDDEN",
                    message="Password input is implicit when password provider is configured",
                    path=f"entities.{name}.fields.password",
                    hint="Remove the password field from YAML",
                )
            )
        if "passwordHash" in fields:
            errors.append(
                ConfigError(
                    code="AUTH_PASSWORD_HASH_FIELD_FORBIDDEN",
                    message="passwordHash is implicit storage when password provider is configured",
                    path=f"entities.{name}.fields.passwordHash",
                    hint="Remove the passwordHash field from YAML",
                )
            )
    return errors


def _validate_roles_field(
    entity_name: str,
    roles_field: str,
    fields: dict[str, Any],
) -> list[ConfigError]:
    if roles_field not in fields:
        return [
            ConfigError(
                code="AUTH_ROLES_FIELD_NOT_FOUND",
                message=f"Roles field '{roles_field}' not found in entity '{entity_name}'",
                path=f"entities.{entity_name}.roles",
            )
        ]
    field_cfg = fields[roles_field]
    if not isinstance(field_cfg, dict) or field_cfg.get("type") != "enum":
        return [
            ConfigError(
                code="AUTH_ROLES_FIELD_NOT_ENUM",
                message=f"Roles field '{roles_field}' must be of type 'enum'",
                path=f"entities.{entity_name}.fields.{roles_field}",
            )
        ]
    return []


def _parse_role_hierarchies(
    roles_data: dict[str, Any],
    auth_entities: set[str],
) -> tuple[dict[str, dict[str, list[str]]], list[ConfigError]]:
    errors: list[ConfigError] = []
    hierarchies: dict[str, dict[str, list[str]]] = {}

    for entity_name, role_map in roles_data.items():
        if entity_name not in auth_entities:
            errors.append(
                ConfigError(
                    code="ROLES_UNKNOWN_ENTITY",
                    message=f"Role hierarchy references unknown auth entity '{entity_name}'",
                    path=f"roles.{entity_name}",
                )
            )
            continue
        if not isinstance(role_map, dict):
            continue
        hierarchies[entity_name] = {
            role: list(includes) if isinstance(includes, list) else []
            for role, includes in role_map.items()
        }

    return hierarchies, errors


def _parse_providers(
    raw: dict[str, Any],
) -> tuple[dict[str, IRProvider], list[ConfigError]]:
    errors: list[ConfigError] = []
    result: dict[str, IRProvider] = {}
    for name, cfg in raw.items():
        provider_type = cfg.get("type")
        if provider_type == "oidc":
            discovery_url = cfg.get("discovery_url") or WELL_KNOWN_OIDC_DISCOVERY.get(name)
            if not discovery_url:
                errors.append(ConfigError(
                    code="OIDC_UNKNOWN_PROVIDER",
                    message=f"Unknown OIDC provider '{name}' — add a discovery_url or use a well-known name",
                    path=f"providers.{name}",
                    hint=f"Well-known names: {', '.join(WELL_KNOWN_OIDC_DISCOVERY)}",
                ))
                continue
            result[name] = IROIDCProvider(
                name=name,
                client_id=cfg["client_id"],
                client_secret=cfg["client_secret"],
                discovery_url=discovery_url,
            )
        elif provider_type == "saml":
            result[name] = IRSAMLProvider(
                name=name,
                idp_metadata_url=cfg["idp_metadata_url"],
                sp_entity_id=cfg["sp_entity_id"],
            )
        else:
            errors.append(ConfigError(
                code="PROVIDER_UNKNOWN_TYPE",
                message=f"Provider '{name}' has unknown type '{provider_type}'",
                path=f"providers.{name}.type",
                hint="Supported types: oidc, saml",
            ))
    return result, errors


class V02Transformer:
    def transform(self, resolved: dict[str, Any]) -> IRDocument:
        api_data: dict[str, Any] = resolved.get("api", {})
        defaults = api_data.get("operations", {}).get("defaults", {})
        import_map = _resolve_imports(resolved.get("imports", {}))
        entities_data: dict[str, Any] = resolved.get("entities", {})
        repos_data: dict[str, Any] = resolved.get("repositories", {})
        services_data: dict[str, Any] = resolved.get("services", {})
        controllers_data: dict[str, Any] = resolved.get("controllers", {})
        roles_data: dict[str, Any] = resolved.get("roles", {})
        providers_data: dict[str, Any] = resolved.get("providers", {})

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

        providers: dict[str, IRProvider] = {}
        if providers_data:
            providers, provider_errors = _parse_providers(providers_data)
            if provider_errors:
                raise ConfigErrors(provider_errors)

        collections, id_errors = self._build_collections(
            entities_data, repos_data, defaults
        )
        if id_errors:
            raise ConfigErrors(id_errors)

        identity_collections = self._build_identity_collections(
            entities_data, collections, providers
        )

        field_errors = _validate_implicit_auth_fields(collections, identity_collections)
        if field_errors:
            raise ConfigErrors(field_errors)

        # Parse role hierarchies
        role_hierarchies: dict[str, dict[str, list[str]]] = {}
        if roles_data:
            role_hierarchies, role_errors = _parse_role_hierarchies(
                roles_data, auth_entities
            )
            if role_errors:
                raise ConfigErrors(role_errors)

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
            role_hierarchies=role_hierarchies,
            providers=providers,
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
        providers: dict[str, IRProvider],
    ) -> dict[str, IRIdentityCollection]:
        _BUILTIN_PROVIDERS = {"password", "apiKey"}
        identity_collections: dict[str, IRIdentityCollection] = {}

        for name, entity_data in entities_data.items():
            if str(entity_data.get("type", "base")) != "auth":
                continue
            plural = name + "s"
            if plural not in collections:
                continue

            fields = collections[plural].fields
            roles_field: str | None = entity_data.get("roles")

            if roles_field is not None:
                role_errors = _validate_roles_field(name, roles_field, fields)
                if role_errors:
                    raise ConfigErrors(role_errors)

            raw_via = entity_data.get("via")
            if not isinstance(raw_via, list) or not raw_via:
                raise ConfigErrors([ConfigError(
                    code="AUTH_VIA_MISSING",
                    message=f"Auth entity '{name}' must define 'via' as a non-empty list of provider bindings",
                    path=f"entities.{name}.via",
                )])

            bindings: list[IRProviderBinding] = []
            binding_errors: list[ConfigError] = []

            for i, raw_binding in enumerate(raw_via):
                binding_path = f"entities.{name}.via[{i}]"
                if not isinstance(raw_binding, dict):
                    binding_errors.append(ConfigError(
                        code="VIA_BINDING_INVALID",
                        message="Each provider binding must be an object",
                        path=binding_path,
                    ))
                    continue

                provider = raw_binding.get("provider")
                identifier = raw_binding.get("identifier")

                if not isinstance(provider, str) or not provider:
                    binding_errors.append(ConfigError(
                        code="VIA_BINDING_PROVIDER_MISSING",
                        message="Provider binding requires a 'provider' string",
                        path=f"{binding_path}.provider",
                    ))
                    continue

                if not isinstance(identifier, str) or not identifier:
                    binding_errors.append(ConfigError(
                        code="VIA_BINDING_IDENTIFIER_MISSING",
                        message="Provider binding requires an 'identifier' string",
                        path=f"{binding_path}.identifier",
                    ))
                    continue

                if identifier not in fields:
                    binding_errors.append(ConfigError(
                        code="VIA_BINDING_IDENTIFIER_NOT_FOUND",
                        message=f"Identifier field '{identifier}' not found in entity '{name}'",
                        path=f"{binding_path}.identifier",
                    ))
                    continue

                if provider not in _BUILTIN_PROVIDERS and provider not in providers:
                    binding_errors.append(ConfigError(
                        code="VIA_UNKNOWN_PROVIDER",
                        message=f"Provider '{provider}' is not built-in and not defined in top-level providers",
                        path=f"{binding_path}.provider",
                        hint="Define it under the top-level 'providers:' section",
                    ))
                    continue

                raw_mapping = raw_binding.get("claim_mapping")
                claim_mapping: dict[str, str] = {}
                if isinstance(raw_mapping, dict):
                    claim_mapping = {str(k): str(v) for k, v in raw_mapping.items()}

                raw_ap = raw_binding.get("auto_provision")
                auto_provision: bool = True if raw_ap is None else bool(raw_ap)

                bindings.append(IRProviderBinding(
                    provider=provider,
                    identifier=identifier,
                    claim_mapping=claim_mapping,
                    auto_provision=auto_provision,
                ))

            if binding_errors:
                raise ConfigErrors(binding_errors)

            identity_collections[plural] = IRIdentityCollection(
                name=plural,
                bindings=tuple(bindings),
                roles_field=roles_field,
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
