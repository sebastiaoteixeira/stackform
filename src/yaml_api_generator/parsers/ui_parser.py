from __future__ import annotations

import re
from typing import Any, NamedTuple

from yaml_api_generator.ir import IRDocument, flatten_role_hierarchy
from yaml_api_generator.ir.api import IRAccessRule, IRIdentityCollection, IRRoute
from yaml_api_generator.ir.ui import (
    AuthProviderInfo,
    ComponentNode,
    EntityFieldInfo,
    EntityInfo,
    GeneratorContext,
    PackComponentDef,
    PackComponentProp,
    PropValue,
    RolesInfo,
    RouteInfo,
    UICollection,
    UICollectionField,
    UIComponent,
    UIView,
)
from yaml_api_generator.ir.pack_manifest import PackManifest

CRUD_OPS = frozenset({"list", "get", "create", "update", "replace", "delete"})
ENTITY_OPS = CRUD_OPS | {"login"}
ANONYMOUS = "anonymous"


def build_generator_context(
    ir: IRDocument,
    ui_block: dict[str, Any],
    manifest: PackManifest,
) -> GeneratorContext:
    base_url = _base_url(ir)
    entities = _build_entities(ir, base_url)
    identity_entities = [
        ir.collections[k].entity_name for k in ir.identityCollections.keys()
    ]
    collections = _parse_collections(ui_block.get("collections", {}), entities, ir)
    pack_components = _parse_pack_components(manifest)
    components = _parse_components(ui_block.get("components", {}), pack_components)
    views = _parse_views(ui_block.get("views", {}), components, pack_components)

    return GeneratorContext(
        api_name=(ir.api.basePath or "").strip("/") or "api",
        api_version=ir.api.version or "",
        base_url=base_url,
        collections=collections,
        components=components,
        views=views,
        pack_components=pack_components,
        pack_scaffold=manifest.scaffold,
        pack_config=ui_block.get("config", {}),
        entities=entities,
        identity_entities=identity_entities,
        session_delivery=ir.session.delivery,
    )


class _Principal(NamedTuple):
    collection: str
    held_roles: frozenset[str]


def _build_entities(ir: IRDocument, base_url: str) -> dict[str, EntityInfo]:
    served = [
        (ir.services[route.service].repository, route)
        for route in ir.routes
        if route.operation in ENTITY_OPS
        and route.service in ir.services
        and ir.services[route.service].repository
    ]
    principals = _principal_columns(ir)
    return {
        ir_col.entity_name: _build_entity(
            ir,
            col_name,
            [route for repository, route in served if repository == col_name],
            base_url,
            principals,
        )
        for col_name, ir_col in ir.collections.items()
    }


def _build_entity(
    ir: IRDocument,
    col_name: str,
    served: list[IRRoute],
    base_url: str,
    principals: dict[str, _Principal | None],
) -> EntityInfo:
    ir_col = ir.collections[col_name]
    identity = ir.identityCollections.get(col_name)
    routes = _first_routes(served, identity is not None)
    password = identity.get_binding("password") if identity else None
    list_route = routes.get("list")
    return EntityInfo(
        name=ir_col.entity_name,
        fields={
            name: _field_info(name, config)
            for name, config in ir_col.fields.items()
            if isinstance(config, dict) and config.get("type", "string") != "id"
        },
        is_auth=identity is not None,
        pk_field=ir_col.idField,
        repository_name=col_name,
        auth_identifier=password.identifier if password else None,
        auth_providers=[
            AuthProviderInfo(name=b.provider, type=ir.providers[b.provider].type)
            for b in (identity.bindings if identity else ())
            if b.provider not in ("password", "apiKey") and b.provider in ir.providers
        ],
        routes={
            op: RouteInfo(method=route.method, path=route.path.removeprefix(base_url))
            for op, route in routes.items()
        },
        pagination=list_route.pagination if list_route else None,
        roles=_roles_info(identity) if identity else None,
        access={
            op: {column: _verdict(route, principal) for column, principal in principals.items()}
            for op, route in routes.items()
            if op in CRUD_OPS
        },
    )


def _field_info(name: str, config: dict[str, Any]) -> EntityFieldInfo:
    return EntityFieldInfo(
        name=name,
        type=config.get("type", "string"),
        required=config.get("required", False),
        unique=config.get("unique", False),
        enum_values=config.get("values"),
        ref_entity=config.get("ref"),
        default=config.get("default"),
        readonly=config.get("readonly", False),
    )


def _first_routes(served: list[IRRoute], is_identity: bool) -> dict[str, IRRoute]:
    first = dict((route.operation, route) for route in reversed(served))
    register = next(
        (route for route in served if route.operation == "create" and route.is_public),
        None,
    )
    return first | ({"register": register} if is_identity and register else {})


def _roles_info(identity: IRIdentityCollection) -> RolesInfo | None:
    if identity.roles is None:
        return None
    includes = flatten_role_hierarchy(identity.roles.hierarchy)
    return RolesInfo(
        values=identity.roles.values,
        default=identity.roles.default,
        field=identity.roles_field,
        includes={role: tuple(sorted(includes.get(role, ()))) for role in identity.roles.values},
    )


def _principal_columns(ir: IRDocument) -> dict[str, _Principal | None]:
    """Columns of the access matrix: anonymous callers, then every identity role."""
    return {ANONYMOUS: None} | {
        column: principal
        for col_name, identity in ir.identityCollections.items()
        for column, principal in _identity_principals(
            ir.collections[col_name].entity_name, col_name, _roles_info(identity)
        ).items()
    }


def _identity_principals(
    entity_name: str, col_name: str, roles: RolesInfo | None
) -> dict[str, _Principal]:
    if roles is None:
        return {entity_name: _Principal(col_name, frozenset())}
    return {
        f"{entity_name}.{role}": _Principal(col_name, frozenset({role, *roles.includes[role]}))
        for role in roles.values
    }


def _verdict(route: IRRoute, principal: _Principal | None) -> str:
    if route.is_public:
        return "allow"
    if principal is None:
        return "deny"
    if not route.access_rules:
        return "allow"
    rule = next((rule for rule in route.access_rules if _rule_matches(rule, principal)), None)
    if rule is None:
        return "deny"
    return "conditional" if rule.when or rule.document_symbols else rule.effect


def _rule_matches(rule: IRAccessRule, principal: _Principal) -> bool:
    return (
        not rule.principal or rule.principal == f"identity:{principal.collection}"
    ) and (rule.required_role is None or rule.required_role in principal.held_roles)


def _base_url(ir: IRDocument) -> str:
    base_path = (ir.api.basePath or "").rstrip("/")
    return f"{base_path}/{ir.api.version}" if ir.api.version else base_path


def _parse_collections(
    raw: dict[str, Any] | None,
    entities: dict[str, EntityInfo],
    ir: IRDocument,
) -> dict[str, UICollection]:
    if not raw:
        return {}
    result: dict[str, UICollection] = {}
    for col_name, col_raw in raw.items():
        fields_raw = col_raw.get("fields", {})
        fields: dict[str, UICollectionField] = {}
        for field_name, field_raw in fields_raw.items():
            from_path = field_raw.get("from", "")
            if not from_path:
                raise ValueError(
                    f"Collection '{col_name}' field '{field_name}' missing 'from' path"
                )
            parts = from_path.split(".")
            source_entity = parts[0]
            source_field_path = parts[1:]

            _validate_from_path(
                col_name, field_name, source_entity, source_field_path, entities, ir
            )

            resolved_type = _resolve_field_type(
                source_entity, source_field_path, entities, ir
            )

            fields[field_name] = UICollectionField(
                name=field_name,
                from_path=from_path,
                source_entity=source_entity,
                source_field_path=source_field_path,
                format=field_raw.get("format"),
                resolved_type=resolved_type,
            )
        result[col_name] = UICollection(name=col_name, fields=fields)
    return result


def _validate_from_path(
    col_name: str,
    field_name: str,
    source_entity: str,
    source_field_path: list[str],
    entities: dict[str, EntityInfo],
    ir: IRDocument,
) -> None:
    entity = entities.get(source_entity)
    if entity is None:
        raise ValueError(
            f"Collection '{col_name}' field '{field_name}': "
            f"unknown entity '{source_entity}'"
        )
    current_entity = entity
    for i, segment in enumerate(source_field_path):
        field_info = current_entity.fields.get(segment)
        if field_info is None:
            raise ValueError(
                f"Collection '{col_name}' field '{field_name}': "
                f"entity '{current_entity.name}' has no field '{segment}'"
            )
        if field_info.type == "ref" and i < len(source_field_path) - 1:
            ref_entity = field_info.ref_entity
            if not ref_entity or ref_entity not in entities:
                raise ValueError(
                    f"Collection '{col_name}' field '{field_name}': "
                    f"ref field '{segment}' points to unknown entity '{ref_entity}'"
                )
            current_entity = entities[ref_entity]


def _resolve_field_type(
    source_entity: str,
    source_field_path: list[str],
    entities: dict[str, EntityInfo],
    ir: IRDocument,
) -> str | None:
    entity = entities.get(source_entity)
    if not entity or not source_field_path:
        return None
    current_entity = entity
    for i, segment in enumerate(source_field_path):
        field_info = current_entity.fields.get(segment)
        if not field_info:
            return None
        if field_info.type == "ref" and i < len(source_field_path) - 1:
            ref_entity = field_info.ref_entity
            if not ref_entity or ref_entity not in entities:
                return None
            current_entity = entities[ref_entity]
        else:
            return field_info.type
    return None


def _parse_components(
    raw: dict[str, Any] | None,
    pack_components: dict[str, PackComponentDef],
) -> dict[str, UIComponent]:
    if not raw:
        return {}
    result: dict[str, UIComponent] = {}
    for comp_name, comp_raw in raw.items():
        props_raw = comp_raw.get("props", {})
        props: dict[str, bool] = {}
        for prop_name, prop_cfg in props_raw.items():
            if isinstance(prop_cfg, dict):
                props[prop_name] = prop_cfg.get("required", False)
            else:
                props[prop_name] = False

        render_raw = comp_raw.get("render", {})
        render = _parse_component_node(render_raw, pack_components)

        _validate_component_refs(comp_name, render, props)

        result[comp_name] = UIComponent(name=comp_name, props=props, render=render)
    return result


def _parse_component_node(
    raw: dict[str, Any],
    pack_components: dict[str, PackComponentDef],
    user_components: dict[str, UIComponent] | None = None,
) -> ComponentNode:
    component_name = raw.get("component", "")
    if not component_name:
        raise ValueError("Component node missing 'component' field")
    all_known = set(pack_components)
    if user_components:
        all_known |= set(user_components)
    if component_name not in all_known:
        raise ValueError(
            f"Component '{component_name}' not found in pack. "
            f"Available: {sorted(all_known)}"
        )

    pack_def = pack_components.get(component_name)
    props_raw = raw.get("props", {})
    props: dict[str, PropValue] = {}
    for prop_name, prop_val in props_raw.items():
        declared_type = None
        if pack_def and prop_name in pack_def.props:
            declared_type = pack_def.props[prop_name].type
        props[prop_name] = _parse_prop_value(
            prop_val, pack_components, declared_type=declared_type
        )

    return ComponentNode(component=component_name, props=props)


def _parse_prop_value(
    raw: Any,
    pack_components: dict[str, PackComponentDef],
    declared_type: str | None = None,
) -> PropValue:
    if isinstance(raw, str) and raw.startswith("$"):
        return PropValue(kind="ref", value=raw[1:])
    if isinstance(raw, dict) and "component" in raw:
        node = _parse_component_node(raw, pack_components)
        return PropValue(kind="component", value=node)
    if declared_type == "component" and isinstance(raw, str):
        return PropValue(kind="component_ref", value=raw)
    return PropValue(kind="literal", value=raw)


def _validate_component_refs(
    comp_name: str,
    node: ComponentNode,
    declared_props: dict[str, bool],
) -> None:
    """Ensure $ref values in the render tree match declared component props."""
    for prop_name, prop_val in node.props.items():
        if prop_val.kind == "ref" and prop_val.value not in declared_props:
            raise ValueError(
                f"Component '{comp_name}': render uses $ref '{prop_val.value}' "
                f"but it's not in declared props: {list(declared_props.keys())}"
            )
        if prop_val.kind == "component":
            _validate_component_refs(comp_name, prop_val.value, declared_props)


def _parse_views(
    raw: dict[str, Any] | None,
    components: dict[str, UIComponent],
    pack_components: dict[str, PackComponentDef],
) -> dict[str, UIView]:
    if not raw:
        return {}
    result: dict[str, UIView] = {}
    for view_name, view_raw in raw.items():
        path = view_raw.get("path", "")
        component = view_raw.get("component", "")
        if not component:
            raise ValueError(f"View '{view_name}' missing 'component'")
        if component not in components and component not in pack_components:
            raise ValueError(
                f"View '{view_name}': component '{component}' not found "
                f"in YAML components or pack components"
            )

        pack_def = pack_components.get(component)
        props_raw = view_raw.get("props", {})
        props: dict[str, PropValue] = {}
        for prop_name, prop_val in props_raw.items():
            declared_type = None
            if pack_def and prop_name in pack_def.props:
                declared_type = pack_def.props[prop_name].type
            props[prop_name] = _parse_prop_value(
                prop_val, pack_components, declared_type=declared_type
            )

        result[view_name] = UIView(
            name=view_name, path=path, component=component, props=props
        )
    return result


def _parse_pack_components(
    manifest: PackManifest,
) -> dict[str, PackComponentDef]:
    result: dict[str, PackComponentDef] = {}
    for comp_name, comp_raw in manifest.components.items():
        props_raw = comp_raw.get("props", {})
        props: dict[str, PackComponentProp] = {}
        for prop_name, prop_cfg in props_raw.items():
            if isinstance(prop_cfg, dict):
                props[prop_name] = PackComponentProp(
                    name=prop_name,
                    type=prop_cfg.get("type"),
                    required=prop_cfg.get("required", False),
                    default=prop_cfg.get("default"),
                )
            else:
                props[prop_name] = PackComponentProp(name=prop_name)
        result[comp_name] = PackComponentDef(name=comp_name, props=props)
    return result


def _to_label(name: str) -> str:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    spaced = spaced.replace("_", " ")
    return spaced.strip().title()
