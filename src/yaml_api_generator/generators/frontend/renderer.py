from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from yaml_api_generator.ir.ui import GeneratorContext, UIView
from .output import OutputFile
from yaml_api_generator.ir.pack_manifest import Pack


def render_templates(pack: Pack, context: GeneratorContext) -> list[OutputFile]:
    env = _create_jinja_env(pack.templates_dir)
    files: list[OutputFile] = []

    files.extend(_render_scaffold(env, pack, context))
    files.extend(_render_data_layer(env, pack, context))
    files.extend(_render_views(env, pack, context))

    return files


def _render_scaffold(
    env: Environment, pack: Pack, context: GeneratorContext
) -> list[OutputFile]:
    files: list[OutputFile] = []
    output = pack.manifest.output
    ext = output.extension

    _ROOT_ITEMS = {
        "package.json",
        "index.html",
        "vite.config.ts",
        "tsconfig.json",
        "tsconfig.node.json",
        "tailwind.config.js",
        "postcss.config.js",
    }

    for item in context.pack_scaffold:
        template_path = f"scaffold/{item}.jinja"
        content = _try_render(
            env,
            template_path,
            {
                "context": context,
                "views": context.views,
                "entities": context.entities,
                "collections": context.collections,
                "pack_config": context.pack_config,
            },
        )
        if content is not None:
            if item in _ROOT_ITEMS:
                out_path = item
            elif "." in item:
                out_path = f"{output.generated_dir}/{item}"
            else:
                out_path = f"{output.generated_dir}/{item}.{ext}"
            files.append(
                OutputFile(
                    path=out_path,
                    content=content,
                    zone="generated",
                )
            )

    return files


def _render_data_layer(
    env: Environment, pack: Pack, context: GeneratorContext
) -> list[OutputFile]:
    files: list[OutputFile] = []
    output = pack.manifest.output
    ext = output.extension

    content = _try_render(
        env,
        "types/index.jinja",
        {
            "context": context,
            "entities": context.entities,
            "collections": context.collections,
            "pack_config": context.pack_config,
        },
    )
    if content is not None:
        files.append(
            OutputFile(
                path=f"{output.generated_dir}/types/index.{ext}",
                content=content,
                zone="generated",
            )
        )

    content = _try_render(
        env,
        "lib/api.jinja",
        {
            "context": context,
            "entities": context.entities,
            "pack_config": context.pack_config,
        },
    )
    if content is not None:
        files.append(
            OutputFile(
                path=f"{output.generated_dir}/lib/api.{ext}",
                content=content,
                zone="generated",
            )
        )

    for col_name, collection in context.collections.items():
        source_entity = None
        for field in collection.fields.values():
            source_entity = context.entities.get(field.source_entity)
            if source_entity:
                break
        content = _try_render(
            env,
            "hooks/useCollection.jinja",
            {
                "collection": collection,
                "entity": source_entity,
                "context": context,
                "pack_config": context.pack_config,
            },
        )
        if content is not None:
            files.append(
                OutputFile(
                    path=f"{output.hooks_dir}/use{_pascal(col_name)}.{ext}",
                    content=content,
                    zone="generated",
                )
            )

    for entity_name, entity in context.entities.items():
        if not entity.repository_name:
            continue
        content = _try_render(
            env,
            "hooks/useMutation.jinja",
            {
                "entity": entity,
                "context": context,
                "pack_config": context.pack_config,
            },
        )
        if content is not None:
            files.append(
                OutputFile(
                    path=f"{output.hooks_dir}/use{_pascal(entity_name)}Mutation.{ext}",
                    content=content,
                    zone="generated",
                )
            )

    for entity_name in context.identity_entities:
        entity = context.entities.get(entity_name)
        if not entity:
            continue
        content = _try_render(
            env,
            "hooks/useAuth.jinja",
            {
                "entity": entity,
                "context": context,
                "pack_config": context.pack_config,
            },
        )
        if content is not None:
            files.append(
                OutputFile(
                    path=f"{output.hooks_dir}/use{_pascal(entity_name)}Auth.{ext}",
                    content=content,
                    zone="generated",
                )
            )

    return files


def _render_views(
    env: Environment, pack: Pack, context: GeneratorContext
) -> list[OutputFile]:
    files: list[OutputFile] = []
    output = pack.manifest.output
    ext = output.extension

    for view_name, view in context.views.items():
        pack_component = _resolve_pack_component(view, context)
        component_tree = _build_component_tree(view, context)

        collection = None
        for prop_val in view.props.values():
            if prop_val.kind == "literal" and isinstance(prop_val.value, str):
                col_ref = _parse_collection_ref(prop_val.value)
                if col_ref and col_ref in context.collections:
                    collection = context.collections[col_ref]
                    break

        entity = None
        for prop_val in view.props.values():
            if prop_val.kind == "literal" and isinstance(prop_val.value, str):
                if prop_val.value in context.entities:
                    entity = context.entities[prop_val.value]
                    break

        if pack_component == "auth" and entity is None:
            for eid in context.identity_entities:
                entity = context.entities.get(eid)
                if entity:
                    break

        template_path = f"components/{pack_component}.jinja"
        content = _try_render(
            env,
            template_path,
            {
                "view": view,
                "collection": collection,
                "entity": entity,
                "context": context,
                "pack_config": context.pack_config,
                "component_tree": component_tree,
                "props": view.props,
            },
        )
        if content is not None:
            files.append(
                OutputFile(
                    path=f"{output.pages_dir}/{_pascal(view_name)}.{ext}",
                    content=content,
                    zone="editable",
                )
            )

    return files


def _resolve_pack_component(view: UIView, context: GeneratorContext) -> str:
    """Get the pack component name for a view. If the view uses a YAML component,
    follow through to its render tree to get the root pack component."""
    if view.component in context.pack_components:
        return view.component
    yaml_comp = context.components.get(view.component)
    if yaml_comp:
        return yaml_comp.render.component
    return view.component


def _build_component_tree(view: UIView, context: GeneratorContext) -> dict[str, Any]:
    """Build a serializable component tree for the template."""
    tree: dict[str, Any] = {"component": view.component, "props": {}}

    yaml_comp = context.components.get(view.component)
    if yaml_comp:
        tree["render"] = _component_node_to_dict(yaml_comp.render)
        tree["declared_props"] = yaml_comp.props

    for prop_name, prop_val in view.props.items():
        tree["props"][prop_name] = _prop_value_to_dict(prop_val)

    return tree


def _component_node_to_dict(node: Any) -> dict[str, Any]:
    from yaml_api_generator.ir.ui import ComponentNode

    if not isinstance(node, ComponentNode):
        return {}
    result: dict[str, Any] = {"component": node.component, "props": {}}
    for prop_name, prop_val in node.props.items():
        result["props"][prop_name] = _prop_value_to_dict(prop_val)
    return result


def _prop_value_to_dict(prop_val: Any) -> dict[str, Any]:
    from yaml_api_generator.ir.ui import PropValue, ComponentNode

    if not isinstance(prop_val, PropValue):
        return {"kind": "literal", "value": prop_val}
    if prop_val.kind == "component" and isinstance(prop_val.value, ComponentNode):
        return {
            "kind": "component",
            "value": _component_node_to_dict(prop_val.value),
        }
    return {"kind": prop_val.kind, "value": prop_val.value}


def _parse_collection_ref(value: str) -> str | None:
    """Extract collection name from reference like 'post-feed' or 'post-feed[id]'."""
    match = re.match(r"^([a-zA-Z0-9_-]+)(?:\[[a-zA-Z0-9_]+\])?$", value)
    if match:
        return match.group(1)
    return None


def _create_jinja_env(templates_dir: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["pascal_case"] = _pascal
    env.filters["camel_case"] = _camel
    env.filters["snake_case"] = _snake
    env.filters["kebab_case"] = _kebab
    return env


def _try_render(
    env: Environment, template_path: str, variables: dict[str, Any]
) -> str | None:
    try:
        template = env.get_template(template_path)
    except TemplateNotFound:
        return None
    return template.render(**variables)


def _pascal(name: str) -> str:
    parts = re.split(r"[_\-\s]+", name)
    parts = [
        sub
        for word in parts
        for sub in re.sub(r"([a-z])([A-Z])", r"\1_\2", word).split("_")
    ]
    return "".join(word.capitalize() for word in parts if word)


def _camel(name: str) -> str:
    p = _pascal(name)
    return p[0].lower() + p[1:] if p else ""


def _snake(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s = re.sub(r"[_\-\s]+", "_", s)
    return s.lower()


def _kebab(name: str) -> str:
    return _snake(name).replace("_", "-")
