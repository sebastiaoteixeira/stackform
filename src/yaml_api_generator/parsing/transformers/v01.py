from typing import Any, cast

from ...ir import (
    IRApi,
    IRCollection,
    IRDocument,
    IRIdentityCollection,
    IROIDCProvider,
    IRProvider,
    IRProviderBinding,
    IRSAMLProvider,
    IRMongo,
    IRRoute,
    WELL_KNOWN_OIDC_DISCOVERY,
)
from ..parser import ConfigError, ConfigErrors

OPERATION_NAMES = ("list", "get", "create", "update", "replace", "delete")
ROUTE_MAPPING: dict[str, tuple[str, str]] = {
    "list": ("GET", "/{collection}"),
    "get": ("GET", "/{collection}/{id}"),
    "create": ("POST", "/{collection}"),
    "update": ("PATCH", "/{collection}/{id}"),
    "replace": ("PUT", "/{collection}/{id}"),
    "delete": ("DELETE", "/{collection}/{id}"),
}


def _normalize_operations(
    global_defaults: dict[str, Any], collection_ops: dict[str, Any] | None
) -> IROperations:
    defaults = {name: True for name in OPERATION_NAMES}
    for name in OPERATION_NAMES:
        if name in global_defaults:
            defaults[name] = bool(global_defaults[name])
    if collection_ops:
        for name in OPERATION_NAMES:
            if name in collection_ops:
                defaults[name] = bool(collection_ops[name])
    return IROperations(**defaults)


def _extract_collection_id_field(
    collection_name: str,
    fields: dict[str, Any],
) -> tuple[str | None, list[ConfigError]]:
    id_fields = [
        field_name
        for field_name, field_config in fields.items()
        if isinstance(field_config, dict) and field_config.get("type") == "id"
    ]

    if len(id_fields) == 1:
        return id_fields[0], []

    if not id_fields:
        return (
            None,
            [
                ConfigError(
                    code="ID_FIELD_MISSING",
                    message="Collection must define exactly one field with type 'id'",
                    path=f"collections.{collection_name}.fields",
                )
            ],
        )

    return (
        None,
        [
            ConfigError(
                code="ID_FIELD_MULTIPLE",
                message="Collection must define exactly one field with type 'id'",
                path=f"collections.{collection_name}.fields",
                hint=f"Found multiple id fields: {', '.join(id_fields)}",
            )
        ],
    )


def _resolve_collection_id_format(
    collection_name: str,
    id_field: str,
    fields: dict[str, Any],
) -> tuple[str | None, list[ConfigError]]:
    field_config = fields.get(id_field)
    if not isinstance(field_config, dict):
        return (
            None,
            [
                ConfigError(
                    code="ID_FIELD_INVALID",
                    message="Collection id field configuration is invalid",
                    path=f"collections.{collection_name}.fields.{id_field}",
                )
            ],
        )

    raw_format = field_config.get("format")
    if raw_format is None:
        return "uuidv7", []

    if raw_format in {"uuidv7", "uuidv4"}:
        return str(raw_format), []

    return (
        None,
        [
            ConfigError(
                code="ID_FORMAT_INVALID",
                message="id field format must be uuidv7 or uuidv4",
                path=f"collections.{collection_name}.fields.{id_field}.format",
            )
        ],
    )


def _build_routes(collection: str, operations: IROperations) -> list[IRRoute]:
    op_map = operations.__dict__
    routes: list[IRRoute] = []
    for operation in OPERATION_NAMES:
        if not op_map[operation]:
            continue
        method, path_template = ROUTE_MAPPING[operation]
        routes.append(
            IRRoute(
                method=method,
                path=path_template.format(collection=collection, id="{id}"),
                operation=operation,
                collection=collection,
            )
        )
    return routes


def _is_operation_public(access_value: Any) -> bool | None:
    if access_value is None:
        return None
    if isinstance(access_value, str):
        normalized = access_value.strip().lower()
        if normalized == "public":
            return True
        if normalized == "authenticated":
            return False
        if normalized.startswith("identity:"):
            return False
        return None
    if not isinstance(access_value, list):
        return None

    saw_rule = False
    for rule in access_value:
        if not isinstance(rule, dict):
            continue

        principal = rule.get("principal")
        principal_type = ""
        if isinstance(principal, str):
            principal_normalized = principal.strip().lower()
            if principal_normalized.startswith("identity:"):
                principal_type = "identity"
            else:
                principal_type = principal_normalized
        if not principal_type:
            continue

        saw_rule = True
        if principal_type == "public":
            return True

    if saw_rule:
        return False
    return None


def _build_routes_with_access_policy(
    collection: str,
    operations: IROperations,
    collection_access: dict[str, Any],
) -> list[IRRoute]:
    op_map = operations.__dict__
    routes: list[IRRoute] = []
    for operation in OPERATION_NAMES:
        if not op_map[operation]:
            continue
        is_public = _is_operation_public(collection_access.get(operation))
        if is_public is None:
            is_public = True
        method, path_template = ROUTE_MAPPING[operation]
        routes.append(
            IRRoute(
                method=method,
                path=path_template.format(collection=collection, id="{id}"),
                operation=operation,
                collection=collection,
                is_public=is_public,
            )
        )
    return routes


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


def _normalize_auth_via(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return cast(list[str], list(value))
    return []


def _extract_identity_bindings(
    collection_name: str,
    collection_data: dict[str, Any],
    fields: dict[str, Any],
    providers: dict[str, IRProvider],
) -> tuple[list[IRProviderBinding], list[ConfigError]]:
    """Build IRProviderBinding list from v0.1 flat auth.identifier + auth.via format."""
    _BUILTIN_VIA = {"password", "apiKey"}
    auth_data = collection_data.get("auth")
    if not isinstance(auth_data, dict):
        return [], []

    identifier: str | None = auth_data.get("identifier")
    via = _normalize_auth_via(auth_data.get("via"))

    if not identifier or not via:
        return [], []

    errors: list[ConfigError] = []
    bindings: list[IRProviderBinding] = []

    raw_mapping = auth_data.get("claim_mapping")
    shared_claim_mapping: dict[str, str] = {}
    if isinstance(raw_mapping, dict):
        shared_claim_mapping = {str(k): str(v) for k, v in raw_mapping.items()}

    raw_ap = auth_data.get("auto_provision")
    shared_auto_provision: bool = True if raw_ap is None else bool(raw_ap)

    for provider in via:
        if provider not in _BUILTIN_VIA and provider not in providers:
            errors.append(ConfigError(
                code="VIA_UNKNOWN_PROVIDER",
                message=f"'{provider}' in auth.via is not a built-in method and not defined in providers",
                path=f"collections.{collection_name}.auth.via",
                hint="Define it under the top-level 'providers:' section",
            ))
            continue
        bindings.append(IRProviderBinding(
            provider=provider,
            identifier=identifier,
            claim_mapping=shared_claim_mapping,
            auto_provision=shared_auto_provision,
        ))

    return bindings, errors


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
                    path=f"collections.{name}.fields.password",
                    hint="Remove the password field from YAML",
                )
            )
        if "passwordHash" in fields:
            errors.append(
                ConfigError(
                    code="AUTH_PASSWORD_HASH_FIELD_FORBIDDEN",
                    message="passwordHash is implicit storage when password provider is configured",
                    path=f"collections.{name}.fields.passwordHash",
                    hint="Remove the passwordHash field from YAML",
                )
            )
    return errors


class V01Transformer:
    def transform(self, resolved: dict[str, Any]) -> IRDocument:
        api: dict[str, Any] = resolved.get("api", {})
        collections_data: dict[str, Any] = resolved["collections"]
        defaults = api.get("operations", {}).get("defaults", {})
        providers_data: dict[str, Any] = resolved.get("providers", {})

        providers: dict[str, IRProvider] = {}
        if providers_data:
            providers, provider_errors = _parse_providers(providers_data)
            if provider_errors:
                raise ConfigErrors(provider_errors)

        collections: dict[str, IRCollection] = {}
        collection_access_policies: dict[str, dict[str, Any]] = {}
        id_field_errors: list[ConfigError] = []
        for name, collection_data in collections_data.items():
            collection_type = str(collection_data.get("type", "base"))
            operations = _normalize_operations(
                defaults, collection_data.get("operations")
            )
            fields = cast(dict[str, Any], collection_data["fields"])
            id_field, errors = _extract_collection_id_field(name, fields)
            id_field_errors.extend(errors)

            id_format: str | None = None
            if id_field is not None:
                id_format, format_errors = _resolve_collection_id_format(
                    name, id_field, fields
                )
                id_field_errors.extend(format_errors)

            raw_access = collection_data.get("access")
            collection_access_policies[name] = (
                raw_access if isinstance(raw_access, dict) else {}
            )

            if id_field is None or id_format is None:
                continue

            collections[name] = IRCollection(
                name=name,
                entity_name=name,
                type=collection_type,
                idField=id_field,
                idFormat=id_format,
                fields=fields,
                operations=operations,
            )

        if id_field_errors:
            raise ConfigErrors(id_field_errors)

        identity_collections: dict[str, IRIdentityCollection] = {}
        auth_errors: list[ConfigError] = []
        for name, collection in collections.items():
            if collection.type != "auth":
                continue
            collection_data = collections_data.get(name, {})
            bindings, id_auth_errors = _extract_identity_bindings(
                name, collection_data, collection.fields, providers
            )
            auth_errors.extend(id_auth_errors)
            identity_collections[name] = IRIdentityCollection(
                name=name,
                bindings=tuple(bindings),
            )
        if auth_errors:
            raise ConfigErrors(auth_errors)

        implicit_field_errors = _validate_implicit_auth_fields(
            collections,
            identity_collections,
        )
        if implicit_field_errors:
            raise ConfigErrors(implicit_field_errors)

        routes: list[IRRoute] = []
        for name, collection in collections.items():
            routes.extend(
                _build_routes_with_access_policy(
                    name,
                    collection.operations,
                    collection_access_policies.get(name, {}),
                )
            )

        for name, identity in identity_collections.items():
            if identity.has_password:
                routes.append(
                    IRRoute(
                        method="POST",
                        path=f"/{name}/login",
                        operation="login",
                        collection=name,
                        is_public=True,
                    )
                )

        mongo_data = resolved.get("mongo", {})
        return IRDocument(
            version=str(resolved["version"]),
            api=IRApi(basePath=api.get("basePath", "/api"), version=api.get("version")),
            collections=collections,
            routes=routes,
            identityCollections=identity_collections,
            providers=providers,
            mongo=IRMongo(
                uri=mongo_data.get("uri", "mongodb://localhost:27017"),
                database=mongo_data.get("database", "yaml_api"),
            ),
        )
