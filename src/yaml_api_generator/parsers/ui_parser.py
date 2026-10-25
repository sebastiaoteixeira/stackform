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
from yaml_api_generator.parsers.errors import ConfigErrors
from yaml_api_generator.parsers.pack_schema import pack_ui_schema
from yaml_api_generator.parsers.yaml_parser import validate_schema

CRUD_OPS = frozenset({"list", "get", "create", "update", "replace", "delete"})
ENTITY_OPS = CRUD_OPS | {"login"}
ANONYMOUS = "anonymous"
LOGIN_PATH = "/login"


def build_generator_context(
    ir: IRDocument,
    ui_block: dict[str, Any],
    manifest: PackManifest,
) -> GeneratorContext:
    base_url = _base_url(ir)
    entities = _build_entities(ir, base_url)
    if errors := validate_schema({"ui": ui_block}, pack_ui_schema(manifest, entities, ui_block)):
        raise ConfigErrors(errors)
    identity_entities = [
        ir.collections[k].entity_name for k in ir.identityCollections.keys()
    ]
    collections = _parse_collections(ui_block.get("collections"), entities)
    pack_components = _parse_pack_components(manifest)
    components = _parse_components(ui_block.get("components", {}), pack_components)
    views = _parse_views(ui_block.get("views", {}), pack_components)
    if not any(entity.serves_login for entity in entities.values()) and any(
        view.path == LOGIN_PATH for view in views.values()
    ):
        raise ValueError(f"View at '{LOGIN_PATH}' signs in with a password, but no identity serves a login route")

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
            name: EntityFieldInfo(name=name, config=config)
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
    raw: dict[str, Any] | None, entities: dict[str, EntityInfo]
) -> dict[str, UICollection]:
    return {name: _parse_collection(name, spec["fields"], entities) for name, spec in (raw or {}).items()}


def _parse_collection(
    name: str, fields_raw: dict[str, Any], entities: dict[str, EntityInfo]
) -> UICollection:
    fields = {field: _project(f"Collection '{name}' field '{field}'", field, spec, entities)
              for field, spec in fields_raw.items()}
    sources = {field.source_entity for field in fields.values()}
    if len(sources) != 1:
        raise ValueError(f"Collection '{name}' projects more than one entity: {sorted(sources)}")
    return UICollection(name=name, entity=sources.pop(), fields=fields)


def _project(
    label: str, name: str, spec: dict[str, Any], entities: dict[str, EntityInfo]
) -> UICollectionField:
    source, *path = spec["from"].split(".")
    return UICollectionField(
        name=name,
        from_path=spec["from"],
        source_entity=source,
        source_field_path=path,
        format=spec.get("format"),
        resolved_type=_follow(label, entities, source, path).type,
    )


def _follow(
    label: str, entities: dict[str, EntityInfo], entity_name: str, path: list[str]
) -> EntityFieldInfo:
    """The field a path ends on; every earlier segment must be a ref the UI reads through its `get` route."""
    entity = entities.get(entity_name)
    if entity is None:
        raise ValueError(f"{label}: unknown entity '{entity_name}'")
    head, *rest = path
    field = entity.fields.get(head)
    if field is None:
        raise ValueError(f"{label}: entity '{entity.name}' has no field '{head}'")
    if not rest:
        return field
    if field.type != "ref":
        raise ValueError(f"{label}: '{entity.name}.{head}' is not a ref")
    target = entities.get(field.ref_entity)
    if target is not None and "get" not in target.operations:
        raise ValueError(f"{label}: '{target.name}' serves no get route to read '{entity.name}.{head}'")
    return _follow(label, entities, field.ref_entity, rest)


def _parse_components(
    raw: dict[str, Any] | None,
    pack_components: dict[str, PackComponentDef],
) -> dict[str, UIComponent]:
    if not raw:
        return {}
    result: dict[str, UIComponent] = {}
    for comp_name, comp_raw in raw.items():
        props = {name: spec.get("required", False) for name, spec in (comp_raw.get("props") or {}).items()}
        render = _parse_component_node(comp_raw["render"], pack_components)
        result[comp_name] = UIComponent(name=comp_name, props=props, render=render)
    return result


def _parse_component_node(
    raw: dict[str, Any],
    pack_components: dict[str, PackComponentDef],
) -> ComponentNode:
    declared = pack_components[raw["component"]].props if raw["component"] in pack_components else {}
    return ComponentNode(
        component=raw["component"],
        props={
            name: _parse_prop_value(value, pack_components, declared_type=declared[name].type if name in declared else None)
            for name, value in (raw.get("props") or {}).items()
        },
    )


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


def _parse_views(
    raw: dict[str, Any] | None,
    pack_components: dict[str, PackComponentDef],
) -> dict[str, UIView]:
    return {
        name: UIView(name=name, path=view["path"], component=node.component, props=node.props)
        for name, view in (raw or {}).items()
        for node in [_parse_component_node(view, pack_components)]
    }


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
