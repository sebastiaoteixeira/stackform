"""The JSON schema a pack's manifest imposes on the ``ui`` block.

``config`` follows the manifest's ``config_schema``; every view and render node
passes only the props its component declares, typed as declared. A ``$name``
string binds a value from elsewhere: any field in a view, and one of the
enclosing component's declared props inside its ``render`` tree.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from yaml_api_generator.ir.pack_manifest import PackManifest

VIEW_BINDING = {"type": "string", "pattern": r"^\$"}


def pack_ui_schema(manifest: PackManifest, entity_names: Iterable[str], ui_block: dict[str, Any]) -> dict[str, Any]:
    user_components = ui_block.get("components") or {}
    grammar = _ComponentGrammar(
        props={
            **{name: spec.get("props") or {} for name, spec in manifest.components.items()},
            **{name: component.get("props") or {} for name, component in user_components.items()},
        },
        entities=entity_names,
        projections=ui_block.get("collections") or {},
    )
    return {
        "type": "object",
        "properties": {
            "ui": {
                "type": "object",
                "properties": {
                    "config": manifest.config_schema,
                    "views": {"additionalProperties": {"$ref": "#/$defs/view"}},
                    "components": {
                        "properties": {
                            name: {"properties": {"render": {"$ref": f"#/$defs/render/{name}"}}}
                            for name in user_components
                        }
                    },
                },
            }
        },
        "$defs": {
            "view": grammar.node(VIEW_BINDING, "#/$defs/view"),
            "render": {
                name: grammar.node({"enum": [f"${prop}" for prop in grammar.props[name]]}, f"#/$defs/render/{name}")
                for name in user_components
            },
        },
    }


class _ComponentGrammar:
    """Component nodes whose props take the kind each component declares."""

    def __init__(self, props: dict[str, dict[str, Any]], entities: Iterable[str], projections: Iterable[str]):
        self.props = props
        names = "|".join(map(re.escape, projections))
        self.kinds: dict[str, dict[str, Any]] = {
            "collection": {"enum": sorted(entities)},
            "projection": {"type": "string", "pattern": rf"^(?=[\w-])({names})(\[\w+\])?$"},
            "component": {"enum": sorted(props)},
            "function": {"not": {}},
        }

    def node(self, binding: dict[str, Any], ref: str) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["component"],
            "properties": {"component": self.kinds["component"]},
            "allOf": [
                {
                    "if": {"required": ["component"], "properties": {"component": {"const": name}}},
                    "then": self._props(declared, binding, ref),
                }
                for name, declared in self.props.items()
            ],
        }

    def _props(self, declared: dict[str, Any], binding: dict[str, Any], ref: str) -> dict[str, Any]:
        required = [name for name, declaration in declared.items() if declaration.get("required")]
        return {
            "required": ["props"] if required else [],
            "properties": {
                "props": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": required,
                    "properties": {
                        name: {"anyOf": [binding, self._typed(declaration, ref)]}
                        for name, declaration in declared.items()
                    },
                }
            },
        }

    def _typed(self, declaration: dict[str, Any], ref: str) -> dict[str, Any]:
        kind = declaration.get("type")
        if kind == "component":
            return {"anyOf": [self.kinds[kind], {"$ref": ref}]}
        return self.kinds.get(kind) or {key: value for key, value in declaration.items() if key != "required"}
