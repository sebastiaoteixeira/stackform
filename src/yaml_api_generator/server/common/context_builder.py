from typing import Any

from yaml_api_generator.ir import (
    IRCollection,
    IRDocument,
    IRDocumentBinding,
    IRIdentityCollection,
    flatten_role_hierarchy,
)
from .auth.jwt import JWKS_PATH
from .server_context import (
    RuntimeAccessRule,
    RuntimeAppConfig,
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeContext,
    RuntimeIdentityDescriptor,
    RuntimeOperationDescriptor,
    RuntimeRouteDescriptor,
    RuntimeSessionConfig,
)


def build_runtime_context(document: IRDocument) -> RuntimeContext:
    app = RuntimeAppConfig(
        base_path=document.api.basePath,
        api_version=document.api.version,
    )

    session = RuntimeSessionConfig(
        algorithm=document.session.algorithm,
        ttl=document.session.ttl,
        refresh=document.session.refresh,
    )
    collections = _build_collections(document.collections)
    routes = _build_routes(document)
    if session.uses_asymmetric:
        routes.append(_jwks_route())
    auth = _build_auth_config(
        document.identityCollections,
        document.collections,
        document.providers,
    )
    operations = _build_operations(document)

    return RuntimeContext(
        app=app,
        collections=collections,
        routes=routes,
        auth=auth,
        operations=operations,
        spec_version=document.version,
        session=session,
    )


def _jwks_route() -> RuntimeRouteDescriptor:
    return RuntimeRouteDescriptor(
        method="GET",
        path=JWKS_PATH,
        operation="jwks",
        collection=None,
        is_public=True,
    )


def _build_operations(
    document: IRDocument,
) -> dict[str, dict[str, RuntimeOperationDescriptor]]:
    return {
        repo_name: {
            op_name: RuntimeOperationDescriptor(
                name=op.name, query=op.query, handler=op.handler
            )
            for op_name, op in repo.operations.items()
        }
        for repo_name, repo in document.repositories.items()
        if repo.operations
    }


def _build_collections(
    ir_collections: dict[str, IRCollection],
) -> dict[str, RuntimeCollectionDescriptor]:
    return {
        name: RuntimeCollectionDescriptor(
            name=col.name,
            type=col.type,
            id_field=col.idField,
            id_format=col.idFormat,
            fields=col.fields,
            datastore=col.datastore,
        )
        for name, col in ir_collections.items()
    }


def _build_routes(document: IRDocument) -> list[RuntimeRouteDescriptor]:
    routes = []
    for route in document.routes:
        access_rules = None
        if route.access_rules:
            access_rules = [
                RuntimeAccessRule(
                    principal=rule.principal,
                    required_role=rule.required_role,
                    identity_symbols=rule.identity_symbols,
                    document_symbols=rule.document_symbols,
                    request_symbols=rule.request_symbols,
                    when=rule.when,
                    effect=rule.effect,
                    reason=rule.reason if document.version == "0.3" else None,
                    bind=rule.bind,
                )
                for rule in route.access_rules
            ]
        service = document.services.get(route.service)
        service_input = (
            service.input.fields if service is not None and service.input is not None else None
        )
        service_forwarding = dict(service.forwarding) if service is not None else {}
        routes.append(
            RuntimeRouteDescriptor(
                method=route.method,
                path=route.path,
                operation=route.operation,
                collection=route.collection,
                is_public=route.is_public,
                handler=route.handler,
                access_rules=access_rules,
                service_input=service_input,
                service_forwarding=service_forwarding,
                pagination=route.pagination,
            )
        )
    if document.session.refresh:
        routes += [_refresh_route(route) for route in routes if route.operation == "login"]
    return routes


def _refresh_route(login: RuntimeRouteDescriptor) -> RuntimeRouteDescriptor:
    return RuntimeRouteDescriptor(
        method="POST",
        path=f"{login.path.removesuffix('/login')}/refresh",
        operation="refresh",
        collection=login.collection,
        is_public=True,
    )


def _build_auth_config(
    identity_collections: dict[str, IRIdentityCollection],
    collections: dict[str, IRCollection],
    providers: dict[str, Any],
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
            bindings=identity.bindings,
            id_field=id_field,
            roles=identity.roles,
            roles_field=identity.roles_field,
        )

        identity_id_fields[name] = id_field

        if identity.has_password:
            has_password = True
        if identity.has_api_key:
            has_api_key = True

    entity_to_collection: dict[str, str] = {
        collections[name].entity_name: name
        for name in identity_collections
        if name in collections and collections[name].entity_name
    }
    flattened_hierarchies: dict[str, dict[str, set[str]]] = {}
    for name, identity in identity_collections.items():
        if identity.roles is not None and identity.roles.hierarchy:
            raw: dict[str, list[str]] = {
                role: list(includes)
                for role, includes in identity.roles.hierarchy.items()
            }
            flattened_hierarchies[name] = flatten_role_hierarchy(raw)

    return RuntimeAuthConfig(
        enabled=bool(identity_collections),
        identity_collections=identity_descriptors,
        identity_id_fields=identity_id_fields,
        has_password_auth=has_password,
        has_api_key_auth=has_api_key,
        role_hierarchies=flattened_hierarchies,
        providers=providers,
    )
