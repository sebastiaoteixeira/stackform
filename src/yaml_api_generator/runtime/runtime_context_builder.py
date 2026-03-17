from ..ir import IRDocument, IRCollection, IRIdentityCollection
from .runtime_context import (
    RuntimeAppConfig,
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeContext,
    RuntimeIdentityDescriptor,
    RuntimeRouteDescriptor,
)


def build_runtime_context(document: IRDocument) -> RuntimeContext:
    app = RuntimeAppConfig(
        base_path=document.api.basePath,
        api_version=document.api.version,
    )

    collections = _build_collections(document.collections)
    routes = _build_routes(document)
    auth = _build_auth_config(document.identityCollections, document.collections)

    return RuntimeContext(
        app=app,
        collections=collections,
        routes=routes,
        auth=auth,
    )


def _build_collections(
    ir_collections: dict[str, IRCollection]
) -> dict[str, RuntimeCollectionDescriptor]:
    return {
        name: RuntimeCollectionDescriptor(
            name=col.name,
            type=col.type,
            id_field=col.idField,
            id_format=col.idFormat,
            fields=col.fields,
        )
        for name, col in ir_collections.items()
    }


def _build_routes(document: IRDocument) -> list[RuntimeRouteDescriptor]:
    routes = []
    for route in document.routes:
        routes.append(
            RuntimeRouteDescriptor(
                method=route.method,
                path=route.path,
                operation=route.operation,
                collection=route.collection,
                is_public=route.is_public,
                handler=route.handler,
            )
        )
    return routes


def _build_auth_config(
    identity_collections: dict[str, IRIdentityCollection],
    collections: dict[str, IRCollection],
) -> RuntimeAuthConfig:
    identity_descriptors: dict[str, RuntimeIdentityDescriptor] = {}
    identity_id_fields: dict[str, str] = {}
    has_password = False
    has_api_key = False

    for name, identity in identity_collections.items():
        collection = collections[name]
        id_field = collection.idField

        identity_descriptors[name] = RuntimeIdentityDescriptor(
            name=identity.name,
            identifier=identity.identifier,
            via=identity.via,
            id_field=id_field,
        )

        identity_id_fields[name] = id_field

        if "password" in identity.via:
            has_password = True
        if "apiKey" in identity.via:
            has_api_key = True

    return RuntimeAuthConfig(
        enabled=bool(identity_collections),
        identity_collections=identity_descriptors,
        identity_id_fields=identity_id_fields,
        has_password_auth=has_password,
        has_api_key_auth=has_api_key,
    )
