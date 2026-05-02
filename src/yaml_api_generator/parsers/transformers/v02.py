
from typing import Any, cast

from yaml_api_generator.ir import (
    IRAccessRule,
    IRApi,
    IRCollection,
    IRCors,
    IRDeploy,
    IRDeployDocker,
    IRDeploySystemd,
    IRDocument,
    IRDocumentBinding,
    IRIdentityBinding,
    IRIdentityCollection,
    IRMongo,
    IROperations,
    IRProviderBinding,
    IRRoute,
    IRService,
)
from yaml_api_generator.parsers.yaml_parser import ConfigError, ConfigErrors
from yaml_api_generator.parsers.when_parser import parse_document_binding, parse_when_list


class V02Transformer:
    _OPERATION_NAMES = ("list", "get", "create", "update", "replace", "delete")

    def transform(self, resolved: dict[str, Any]) -> IRDocument:
        api_data: dict[str, Any] = resolved.get("api", {})
        defaults = api_data.get("operations", {}).get("defaults", {})
        import_map = self._resolve_imports(resolved.get("imports", {}))
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

        collections, id_errors = self._build_collections(
            entities_data, repos_data, defaults
        )
        if id_errors:
            raise ConfigErrors(id_errors)

        identity_collections = self._build_identity_collections(
            entities_data, collections, repo_entity_map
        )

        field_errors = self._validate_implicit_auth_fields(collections, identity_collections)
        if field_errors:
            raise ConfigErrors(field_errors)

        role_hierarchies: dict[str, dict[str, list[str]]] = {}
        if roles_data:
            role_hierarchies, role_errors = self._parse_role_hierarchies(
                roles_data, auth_entities
            )
            if role_errors:
                raise ConfigErrors(role_errors)

        services = self._build_services(services_data, repo_entity_map, import_map)
        routes = self._build_routes(
            controllers_data,
            services,
            api_data,
            repo_entity_map,
            auth_entities,
            entity_to_collection,
        )

        return IRDocument(
            version=str(resolved["version"]),
            api=self._build_api(api_data),
            collections=collections,
            routes=routes,
            identityCollections=identity_collections,
            services=services,
            role_hierarchies=role_hierarchies,
            mongo=self._build_mongo(resolved.get("mongo", {})),
            deploy=self._build_deploy(resolved.get("deploy")),
        )

    def _normalize_operations(
        self, global_defaults: dict[str, Any], repo_ops: dict[str, Any] | None
    ) -> IROperations:
        defaults = {name: True for name in self._OPERATION_NAMES}
        for name in self._OPERATION_NAMES:
            if name in global_defaults:
                defaults[name] = bool(global_defaults[name])
        if repo_ops:
            for name in self._OPERATION_NAMES:
                if name in repo_ops:
                    defaults[name] = bool(repo_ops[name])
        return IROperations(**defaults)

    def _extract_entity_id_field(
        self, entity_name: str, fields: dict[str, Any]
    ) -> tuple[str | None, list[ConfigError]]:
        id_fields = [
            name for name, cfg in fields.items()
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
        self, entity_name: str, id_field: str, fields: dict[str, Any]
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

    def _normalize_via(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return cast(list[str], list(value))
        return []

    def _validate_implicit_auth_fields(
        self,
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

    def _validate_roles_field(
        self, entity_name: str, roles_field: str, fields: dict[str, Any]
    ) -> list[ConfigError]:
        if roles_field not in fields:
            return [
                ConfigError(
                    code="AUTH_ROLES_FIELD_NOT_FOUND",
                    message=f"Roles field '{roles_field}' not found in entity '{entity_name}'",
                    path=f"entities.{entity_name}.auth.roles",
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
        self, roles_data: dict[str, Any], auth_entities: set[str]
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

    def _parse_access_value(
        self,
        access: Any,
        path: str,
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> tuple[bool, list[IRAccessRule] | None, list[ConfigError]]:
        if access is None or access == "public":
            return True, None, []
        if access in ("*", "authenticated"):
            return False, None, []
        if isinstance(access, str):
            rule, errors = self._parse_access_string(
                access, path, auth_entities, entity_to_collection
            )
            if errors:
                return False, None, errors
            return False, ([rule] if rule is not None else None), []
        if isinstance(access, list):
            rules: list[IRAccessRule] = []
            errors: list[ConfigError] = []
            for i, item in enumerate(access):
                item_path = f"{path}[{i}]"
                if isinstance(item, str):
                    rule, str_errors = self._parse_access_string(
                        item, item_path, auth_entities, entity_to_collection
                    )
                    errors.extend(str_errors)
                    if rule is not None:
                        rules.append(rule)
                elif isinstance(item, dict):
                    rule, dict_errors = self._parse_access_rule_object(
                        item, item_path, auth_entities, entity_to_collection
                    )
                    errors.extend(dict_errors)
                    if rule is not None:
                        rules.append(rule)
            if errors:
                return False, None, errors
            return False, (rules if rules else None), []
        return True, None, []

    def _parse_access_string(
        self,
        value: str,
        path: str,
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> tuple[IRAccessRule | None, list[ConfigError]]:
        if value in ("public", "*", "authenticated"):
            return None, []

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
            return IRAccessRule(principal=f"identity:{collection}", required_role=role_part), []

        if not auth_entities:
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
        return IRAccessRule(principal=f"identity:{collection}", required_role=value), []

    def _parse_access_rule_object(
        self,
        rule: dict[str, Any],
        path: str,
        auth_entities: set[str],
        entity_to_collection: dict[str, str],
    ) -> tuple[IRAccessRule | None, list[ConfigError]]:
        errors: list[ConfigError] = []
        given = rule.get("given", {})
        effect = rule.get("then", "allow")

        identity_symbols: dict[str, IRIdentityBinding] = {}
        document_symbols: dict[str, IRDocumentBinding] = {}

        if isinstance(given, dict):
            for symbol_name, symbol_value in given.items():
                if not isinstance(symbol_value, str):
                    continue
                if symbol_value.startswith("identity:"):
                    entity_name = symbol_value[len("identity:"):]
                    collection = entity_to_collection.get(entity_name)
                    if collection is None:
                        errors.append(
                            ConfigError(
                                code="ACCESS_UNKNOWN_ENTITY",
                                message=f"Unknown auth entity '{entity_name}' in access rule",
                                path=f"{path}.given.{symbol_name}",
                            )
                        )
                    else:
                        identity_symbols[symbol_name] = IRIdentityBinding(
                            entity_name=entity_name,
                            collection_name=collection,
                        )
                else:
                    parsed, doc_errors = parse_document_binding(
                        symbol_value, f"{path}.given.{symbol_name}"
                    )
                    errors.extend(doc_errors)
                    if parsed is not None:
                        document_symbols[symbol_name] = IRDocumentBinding(
                            collection=parsed[0], id_param=parsed[1]
                        )

        when_expr = None
        when_raw = rule.get("when")
        if when_raw is not None:
            when_expr, when_errors = parse_when_list(when_raw, f"{path}.when")
            errors.extend(when_errors)

        if errors:
            return None, errors

        first_identity = next(iter(identity_symbols.values()), None)
        principal = f"identity:{first_identity.collection_name}" if first_identity else ""

        return IRAccessRule(
            principal=principal,
            required_role=None,
            identity_symbols=identity_symbols,
            document_symbols=document_symbols,
            when=when_expr,
            effect=effect,
            filter=rule.get("filter"),
            write_fields=rule.get("writeFields", []),
            reason=rule.get("reason"),
        ), []

    def _build_collections(
        self,
        entities_data: dict[str, Any],
        repos_data: dict[str, Any],
        defaults: dict[str, Any],
    ) -> tuple[dict[str, IRCollection], list[ConfigError]]:
        collections: dict[str, IRCollection] = {}
        errors: list[ConfigError] = []

        for repo_name, repo_cfg in repos_data.items():
            if not isinstance(repo_cfg, dict):
                continue
            entity_name = repo_cfg.get("entity")
            if not entity_name:
                continue
            entity_data = entities_data.get(entity_name)
            if not isinstance(entity_data, dict):
                errors.append(
                    ConfigError(
                        code="ENTITY_NOT_FOUND",
                        message=f"Repository '{repo_name}' references unknown entity '{entity_name}'",
                        path=f"repositories.{repo_name}.entity",
                    )
                )
                continue

            entity_type = str(entity_data.get("type", "base"))
            fields = cast(dict[str, Any], entity_data.get("fields", {}))
            operations = self._normalize_operations(defaults, repo_cfg.get("operations"))

            pk_field = entity_data.get("pk")
            if pk_field is not None:
                if pk_field not in fields:
                    errors.append(
                        ConfigError(
                            code="PK_FIELD_NOT_FOUND",
                            message=f"pk field '{pk_field}' not found in entity '{entity_name}'",
                            path=f"entities.{entity_name}.pk",
                        )
                    )
                    continue
                id_field, id_format = pk_field, "natural"
            else:
                id_field_result, id_errors = self._extract_entity_id_field(entity_name, fields)
                errors.extend(id_errors)
                id_format_result: str | None = None
                if id_field_result is not None:
                    id_format_result, fmt_errors = self._resolve_id_format(
                        entity_name, id_field_result, fields
                    )
                    errors.extend(fmt_errors)
                if id_field_result is None or id_format_result is None:
                    continue
                id_field, id_format = id_field_result, id_format_result

            collections[repo_name] = IRCollection(
                name=repo_name,
                entity_name=entity_name,
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
        repo_entity_map: dict[str, str],
    ) -> dict[str, IRIdentityCollection]:
        identity_collections: dict[str, IRIdentityCollection] = {}
        for repo_name, entity_name in repo_entity_map.items():
            entity_data = entities_data.get(entity_name)
            if not isinstance(entity_data, dict):
                continue
            if str(entity_data.get("type", "base")) != "auth":
                continue
            if repo_name not in collections:
                continue
            auth_data = entity_data.get("auth", {})
            identifier = auth_data.get("identifier") if isinstance(auth_data, dict) else None
            via = self._normalize_via(
                auth_data.get("via") if isinstance(auth_data, dict) else None
            )
            roles_field = auth_data.get("roles") if isinstance(auth_data, dict) else None

            if roles_field is not None:
                role_errors = self._validate_roles_field(
                    entity_name, roles_field, collections[repo_name].fields
                )
                if role_errors:
                    raise ConfigErrors(role_errors)

            bindings = tuple(
                IRProviderBinding(provider=p, identifier=identifier or "")
                for p in via
                if identifier
            )
            identity_collections[repo_name] = IRIdentityCollection(
                name=repo_name,
                bindings=bindings,
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

    def _build_api(self, api_data: dict[str, Any]) -> IRApi:
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

    def _build_mongo(self, mongo_data: dict[str, Any]) -> IRMongo:
        return IRMongo(
            uri=mongo_data.get("uri", "mongodb://localhost:27017"),
            database=mongo_data.get("database", "yaml_api"),
        )

    def _build_deploy(self, deploy_data: Any) -> IRDeploy | None:
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
        mongo_data = deploy_data.get("mongo", {})
        return IRDeploy(
            runtime=str(runtime),
            name=deploy_data.get("name"),
            port=int(deploy_data.get("port", 8000)),
            mongo_local=bool(mongo_data.get("local", False)) if isinstance(mongo_data, dict) else False,
            docker=docker,
            systemd=systemd,
        )

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

                is_public, access_rules, access_errors = self._parse_access_value(
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
