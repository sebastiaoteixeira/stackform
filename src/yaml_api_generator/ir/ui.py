from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PropValue:
    kind: str
    value: Any


@dataclass
class ComponentNode:
    component: str
    props: dict[str, PropValue]


@dataclass
class UICollectionField:
    name: str
    from_path: str
    source_entity: str
    source_field_path: list[str]
    format: str | None = None
    resolved_type: str | None = None


@dataclass
class UICollection:
    name: str
    fields: dict[str, UICollectionField]


@dataclass
class UIComponent:
    name: str
    props: dict[str, bool]
    render: ComponentNode


@dataclass
class UIView:
    name: str
    path: str
    component: str
    props: dict[str, PropValue]


@dataclass
class PackComponentProp:
    name: str
    type: str | None = None
    required: bool = False
    default: Any = None


@dataclass
class PackComponentDef:
    name: str
    props: dict[str, PackComponentProp]


@dataclass
class EntityFieldInfo:
    name: str
    type: str
    required: bool = False
    unique: bool = False
    enum_values: list[str] | None = None
    ref_entity: str | None = None
    default: Any = None
    readonly: bool = False


@dataclass
class AuthProviderInfo:
    name: str
    type: str


@dataclass
class EntityInfo:
    name: str
    fields: dict[str, EntityFieldInfo]
    is_auth: bool = False
    pk_field: str = "id"
    repository_name: str | None = None
    auth_identifier: str | None = None
    api_base_path: str | None = None
    auth_providers: list[AuthProviderInfo] = field(default_factory=list)
    operations: frozenset[str] = field(default_factory=frozenset)
    public_operations: frozenset[str] = field(default_factory=frozenset)


@dataclass
class GeneratorContext:
    api_name: str
    api_version: str
    base_url: str
    api_port: int
    collections: dict[str, UICollection]
    components: dict[str, UIComponent]
    views: dict[str, UIView]
    pack_components: dict[str, PackComponentDef]
    pack_scaffold: list[str]
    pack_config: dict[str, Any]
    entities: dict[str, EntityInfo]
    identity_entities: list[str]
    session_delivery: str = "token-url"
