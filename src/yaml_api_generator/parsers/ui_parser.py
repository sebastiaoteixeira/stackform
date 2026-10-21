from __future__ import annotations

import re
from typing import Any

from yaml_api_generator.ir import IRDocument
from yaml_api_generator.ir.ui import (
    AuthProviderInfo,
    ComponentNode,
    EntityFieldInfo,
    EntityInfo,
    GeneratorContext,
    PackComponentDef,
    PackComponentProp,
    PropValue,
    UICollection,
    UICollectionField,
    UIComponent,
    UIView,
)
from yaml_api_generator.ir.pack_manifest import PackManifest

CRUD_OPS = frozenset({"list", "get", "create", "update", "replace", "delete"})


def build_generator_context(
    ir: IRDocument,
    ui_block: dict[str, Any],
    manifest: PackManifest,
) -> GeneratorContext:
    entities = _build_entities(ir)
    identity_entities = [
        ir.collections[k].entity_name for k in ir.identityCollections.keys()
    ]
    collections = _parse_collections(ui_block.get("collections", {}), entities, ir)
    pack_components = _parse_pack_components(manifest)
    components = _parse_components(ui_block.get("components", {}), pack_components)
    views = _parse_views(ui_block.get("views", {}), components, pack_components)

    base_path = ir.api.basePath or ""
    version = ir.api.version or ""
    base_url = base_path.rstrip("/")
    if version:
        base_url = f"{base_url}/{version}"

    return GeneratorContext(
        api_name=base_path.strip("/") or "api",
        api_version=version,
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


def _build_entities(ir: IRDocument) -> dict[str, EntityInfo]:
    entities: dict[str, EntityInfo] = {}
    identity_names = {
        ir.collections[k].entity_name for k in ir.identityCollections.keys()
    }

    base_url = (ir.api.basePath or "").rstrip("/")
    if ir.api.version:
        base_url = f"{base_url}/{ir.api.version}"

    repo_to_base_path: dict[str, str] = {}
    repo_operations: dict[str, set[str]] = {}
    repo_public_operations: dict[str, set[str]] = {}
    for route in ir.routes:
        if not route.service or route.operation not in CRUD_OPS:
            continue
        service = ir.services.get(route.service)
        if not service or not service.repository:
            continue
        repo = service.repository
        repo_operations.setdefault(repo, set()).add(route.operation)
        if route.is_public:
            repo_public_operations.setdefault(repo, set()).add(route.operation)
        if route.operation == "list":
            path = route.path
            if path.startswith(base_url):
                path = path[len(base_url):]
            repo_to_base_path[repo] = path

    for col_name, ir_col in ir.collections.items():
        entity_name = ir_col.entity_name
        fields: dict[str, EntityFieldInfo] = {}
        for field_name, field_config in ir_col.fields.items():
            if not isinstance(field_config, dict):
                continue
            ftype = field_config.get("type", "string")
            if ftype == "id":
                continue
            fields[field_name] = EntityFieldInfo(
                name=field_name,
                type=ftype,
                required=field_config.get("required", False),
                unique=field_config.get("unique", False),
                enum_values=field_config.get("values"),
                ref_entity=field_config.get("ref"),
                default=field_config.get("default"),
                readonly=field_config.get("readonly", False),
            )

        auth_identifier = None
        auth_providers: list[AuthProviderInfo] = []
        identity = ir.identityCollections.get(col_name)
        if identity:
            pw_binding = identity.get_binding("password")
            auth_identifier = pw_binding.identifier if pw_binding else None
            auth_providers = [
                AuthProviderInfo(name=b.provider, type=ir.providers[b.provider].type)
                for b in identity.bindings
                if b.provider not in ("password", "apiKey") and b.provider in ir.providers
            ]

        api_base_path = repo_to_base_path.get(col_name)

        entities[entity_name] = EntityInfo(
            name=entity_name,
            fields=fields,
            is_auth=entity_name in identity_names,
            pk_field=ir_col.idField,
            repository_name=col_name,
            auth_identifier=auth_identifier,
            api_base_path=api_base_path,
            auth_providers=auth_providers,
            operations=frozenset(repo_operations.get(col_name, set())),
            public_operations=frozenset(repo_public_operations.get(col_name, set())),
        )

    return entities


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
