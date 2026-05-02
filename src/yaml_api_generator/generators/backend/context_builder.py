from typing import Any

from ...ir import (
    IRDocument,
    IRCollection,
    IRIdentityCollection,
    IROIDCProvider,
    IRSAMLProvider,
)
from .compile_context import (
    AccessRuleDescriptor,
    AppConfig,
    AuthConfig,
    CompileContext,
    CorsConfig,
    FieldDescriptor,
    IdentityCollectionDescriptor,
    ModelDescriptor,
    RouteDescriptor,
)


WRITE_OPERATIONS = ("create", "update", "replace")


def build_context(document: IRDocument) -> CompileContext:
    cors = None
    if document.api.cors:
        cors = CorsConfig(
            origins=document.api.cors.origins,
            methods=document.api.cors.methods,
            headers=document.api.cors.headers,
            credentials=document.api.cors.credentials,
        )

    app = AppConfig(
        base_path=document.api.basePath,
        api_version=document.api.version,
        cors=cors,
        port=document.api.port,
    )

    identity_map = document.identityCollections
    models = _build_models(document.collections, identity_map)
    model_index = {m.name: m for m in models}
    routes = _build_routes(document, model_index)

    raw_collections: dict[str, Any] = {}
    for name, col in document.collections.items():
        raw_collections[name] = {
            "id_field": col.idField,
            "id_format": col.idFormat,
            "type": col.type,
            "fields": col.fields,
        }

    auth = _build_auth_config(identity_map, document.collections, document.providers)

    return CompileContext(
        app=app,
        models=models,
        routes=routes,
        auth=auth,
        collections=raw_collections,
        role_hierarchies=document.role_hierarchies,
    )


def _build_models(
    collections: dict[str, IRCollection],
    identity_map: dict[str, IRIdentityCollection],
) -> list[ModelDescriptor]:
    models: list[ModelDescriptor] = []
    for name, col in collections.items():
        identity = identity_map.get(name)
        for op in WRITE_OPERATIONS:
            ops_dict = col.operations.__dict__
            if not ops_dict.get(op, False):
                continue
            fields = _build_fields(col, op, identity)
            model_name = _model_name(name, op)
            models.append(
                ModelDescriptor(
                    name=model_name,
                    collection=name,
                    operation=op,
                    fields=fields,
                )
            )

    return models


def _model_name(collection: str, operation: str) -> str:
    col_part = "".join(part.capitalize() for part in collection.split("_"))
    return f"{col_part}{operation.capitalize()}Payload"


def _build_fields(
    col: IRCollection,
    operation: str,
    identity: IRIdentityCollection | None,
) -> list[FieldDescriptor]:
    make_optional = operation == "update"
    fields: list[FieldDescriptor] = []

    for field_name, raw_config in col.fields.items():
        if not isinstance(raw_config, dict):
            continue
        if raw_config.get("type") == "id":
            continue
        if field_name == "_auth":
            continue

        field_type = raw_config.get("type", "string")
        required = bool(raw_config.get("required", False))
        has_default = "default" in raw_config
        default_value: Any = None

        if make_optional:
            is_optional = True
            default_value = raw_config.get("default")
        elif has_default:
            is_optional = False
            default_value = raw_config["default"]
        elif required:
            is_optional = False
            default_value = None
        else:
            is_optional = True
            default_value = None

        constraints: dict[str, Any] = {}
        if raw_config.get("min") is not None:
            constraints["min"] = raw_config["min"]
        if raw_config.get("max") is not None:
            constraints["max"] = raw_config["max"]
        if raw_config.get("minLength") is not None:
            constraints["min_length"] = raw_config["minLength"]
        if raw_config.get("maxLength") is not None:
            constraints["max_length"] = raw_config["maxLength"]
        if raw_config.get("format") is not None:
            constraints["format"] = raw_config["format"]

        enum_values = raw_config.get("values") if field_type == "enum" else None
        array_item_type = None
        if field_type == "array":
            items = raw_config.get("items")
            if isinstance(items, dict):
                array_item_type = items.get("type", "string")

        ref_collection = raw_config.get("ref") if field_type == "ref" else None

        fields.append(
            FieldDescriptor(
                name=field_name,
                type=field_type,
                required=required and not make_optional,
                is_optional=is_optional,
                default=default_value,
                constraints=constraints,
                enum_values=enum_values,
                array_item_type=array_item_type,
                ref_collection=ref_collection,
            )
        )

    if identity is not None and operation == "create" and identity.has_password:
        has_password_field = any(f.name == "password" for f in fields)
        if not has_password_field:
            fields.append(
                FieldDescriptor(
                    name="password",
                    type="string",
                    required=True,
                    is_optional=False,
                    constraints={"min_length": 1},
                )
            )

    return fields


def _build_routes(
    document: IRDocument,
    model_index: dict[str, ModelDescriptor],
) -> list[RouteDescriptor]:
    routes: list[RouteDescriptor] = []
    has_identity = bool(document.identityCollections)

    for ir_route in document.routes:
        needs_auth = not ir_route.is_public and has_identity

        access_rules = None
        if ir_route.access_rules:
            access_rules = [
                AccessRuleDescriptor(
                    principal=rule.principal,
                    when=rule.when,
                    effect=rule.effect,
                )
                for rule in ir_route.access_rules
            ]

        if ir_route.handler is not None or ir_route.collection is None:
            routes.append(
                RouteDescriptor(
                    method=ir_route.method,
                    path=ir_route.path,
                    operation=ir_route.operation,
                    collection=ir_route.collection,
                    id_field=None,
                    id_format=None,
                    is_public=ir_route.is_public,
                    needs_auth=needs_auth,
                    is_identity_create=False,
                    body_model=None,
                    has_id_param="{id}" in ir_route.path,
                    password_via=False,
                    handler=ir_route.handler,
                    access_rules=access_rules,
                )
            )
            continue

        col = document.collections[ir_route.collection]
        identity = document.identityCollections.get(ir_route.collection)
        is_identity_create = identity is not None and ir_route.operation == "create"
        uses_password = identity is not None and identity.has_password

        body_model: str | None = None
        if ir_route.operation in WRITE_OPERATIONS or ir_route.operation == "login":
            model_name = _model_name(ir_route.collection, ir_route.operation)
            if model_name in model_index:
                body_model = model_name

        routes.append(
            RouteDescriptor(
                method=ir_route.method,
                path=ir_route.path,
                operation=ir_route.operation,
                collection=ir_route.collection,
                id_field=col.idField,
                id_format=col.idFormat,
                is_public=ir_route.is_public,
                needs_auth=needs_auth,
                is_identity_create=is_identity_create,
                body_model=body_model,
                has_id_param="{id}" in ir_route.path,
                password_via=uses_password,
                access_rules=access_rules,
            )
        )

    return routes


def _build_auth_config(
    identity_map: dict[str, IRIdentityCollection],
    collections: dict[str, IRCollection],
    providers: dict[str, Any],
) -> AuthConfig:
    if not identity_map:
        return AuthConfig(
            enabled=False,
            identity_collections=[],
            has_password_auth=False,
            has_api_key_auth=False,
            providers=providers,
        )

    descriptors: list[IdentityCollectionDescriptor] = []
    has_password = False
    has_api_key = False
    has_oidc = any(isinstance(p, IROIDCProvider) for p in providers.values())
    has_saml = any(isinstance(p, IRSAMLProvider) for p in providers.values())

    for name, identity in identity_map.items():
        col = collections[name]
        descriptors.append(
            IdentityCollectionDescriptor(
                name=name,
                bindings=list(identity.bindings),
                id_field=col.idField,
                roles_field=identity.roles_field,
            )
        )
        if identity.has_password:
            has_password = True
        if identity.has_api_key:
            has_api_key = True

    return AuthConfig(
        enabled=True,
        identity_collections=descriptors,
        has_password_auth=has_password,
        has_api_key_auth=has_api_key,
        has_oidc_auth=has_oidc,
        has_saml_auth=has_saml,
        providers=providers,
    )
