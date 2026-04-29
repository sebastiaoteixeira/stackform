from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --- Prop/Component tree ---

@dataclass
class PropValue:
    kind: str  # "ref" ($field), "literal", "component"
    value: Any  # field name (str), literal, or ComponentNode


@dataclass
class ComponentNode:
    component: str  # pack component name
    props: dict[str, PropValue]


# --- Layer 1: Collections ---

@dataclass
class UICollectionField:
    name: str
    from_path: str  # "post.title", "post.authorId.displayName"
    source_entity: str  # first segment
    source_field_path: list[str]  # remaining segments
    format: str | None = None
    resolved_type: str | None = None


@dataclass
class UICollection:
    name: str
    fields: dict[str, UICollectionField]


# --- Layer 2: Components ---

@dataclass
class UIComponent:
    name: str
    props: dict[str, bool]  # prop_name -> required
    render: ComponentNode


# --- Layer 3: Views ---

@dataclass
class UIView:
    name: str
    path: str
    component: str  # pack or YAML component name
    props: dict[str, PropValue]


# --- Pack ---

@dataclass
class PackComponentProp:
    name: str
    type: str | None = None  # "collection", "component", "number", etc.
    required: bool = False
    default: Any = None


@dataclass
class PackComponentDef:
    name: str
    props: dict[str, PackComponentProp]


# --- Entity metadata (for forms, types, API client) ---

@dataclass
class EntityFieldInfo:
    name: str
    type: str
    required: bool = False
    unique: bool = False
    enum_values: list[str] | None = None
    ref_entity: str | None = None
    default: Any = None


@dataclass
class EntityInfo:
    name: str
    fields: dict[str, EntityFieldInfo]
    is_auth: bool = False
    pk_field: str = "id"
    repository_name: str | None = None
    auth_identifier: str | None = None


# --- Root context ---

@dataclass
class GeneratorContext:
    api_name: str
    api_version: str
    base_url: str
    collections: dict[str, UICollection]
    components: dict[str, UIComponent]
    views: dict[str, UIView]
    pack_components: dict[str, PackComponentDef]
    pack_scaffold: list[str]
    pack_config: dict[str, Any]
    entities: dict[str, EntityInfo]
    identity_entities: list[str]
    role_hierarchies: dict[str, dict[str, list[str]]]


@dataclass
class OutputFile:
    path: str
    content: str
    zone: str
