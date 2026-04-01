from ..ir import IRDocument, IRCollection, IRDocumentBinding, IRIdentityCollection
from .runtime_context import (
    RuntimeAccessRule,
    RuntimeAppConfig,
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeContext,
    RuntimeDocumentBinding,
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
    auth = _build_auth_config(
        document.identityCollections,
        document.collections,
        document.role_hierarchies,
    )

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


def _map_document_binding(
    binding: IRDocumentBinding | None,
) -> RuntimeDocumentBinding | None:
    if binding is None:
        return None
    return RuntimeDocumentBinding(
        collection=binding.collection,
        id_param=binding.id_param,
    )


def _build_routes(document: IRDocument) -> list[RuntimeRouteDescriptor]:
    routes = []
    for route in document.routes:
        access_rules = None
        if route.access_rules:
            access_rules = [
                RuntimeAccessRule(
                    principal=rule.principal,
                    required_role=rule.required_role,
                    when=rule.when,
                    document=_map_document_binding(rule.document),
                    effect=rule.effect,
                )
                for rule in route.access_rules
            ]
        routes.append(
            RuntimeRouteDescriptor(
                method=route.method,
                path=route.path,
                operation=route.operation,
                collection=route.collection,
                is_public=route.is_public,
                handler=route.handler,
                access_rules=access_rules,
            )
        )
    return routes


def _flatten_hierarchy(
    hierarchy: dict[str, list[str]],
) -> dict[str, set[str]]:
    """Transitively expand role inclusions.

    Given {admin: [moderator], moderator: [user]},
    produces {admin: {moderator, user}, moderator: {user}}.
    """
    flattened: dict[str, set[str]] = {}

    def _expand(role: str) -> set[str]:
        if role in flattened:
            return flattened[role]
        includes = hierarchy.get(role, [])
        result: set[str] = set()
        for included in includes:
            result.add(included)
            result |= _expand(included)
        flattened[role] = result
        return result

    for role in hierarchy:
        _expand(role)

    return flattened


def _build_auth_config(
    identity_collections: dict[str, IRIdentityCollection],
    collections: dict[str, IRCollection],
    role_hierarchies: dict[str, dict[str, list[str]]],
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
            roles_field=identity.roles_field,
        )

        identity_id_fields[name] = id_field

        if "password" in identity.via:
            has_password = True
        if "apiKey" in identity.via:
            has_api_key = True

    # Flatten role hierarchies transitively
    flattened_hierarchies: dict[str, dict[str, set[str]]] = {}
    for entity_name, hierarchy in role_hierarchies.items():
        flattened_hierarchies[entity_name] = _flatten_hierarchy(hierarchy)

    return RuntimeAuthConfig(
        enabled=bool(identity_collections),
        identity_collections=identity_descriptors,
        identity_id_fields=identity_id_fields,
        has_password_auth=has_password,
        has_api_key_auth=has_api_key,
        role_hierarchies=flattened_hierarchies,
    )
