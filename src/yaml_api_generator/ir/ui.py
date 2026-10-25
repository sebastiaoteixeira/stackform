from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from yaml_api_generator.ir.api import IRPagination


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
    entity: str
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


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    """Relative to the API base URL, with `{param}` placeholders."""


@dataclass(frozen=True)
class RolesInfo:
    values: tuple[str, ...]
    default: str
    field: str | None
    includes: dict[str, tuple[str, ...]]
    """Every role each role transitively includes through the entity's hierarchy."""


@dataclass
class EntityInfo:
    name: str
    fields: dict[str, EntityFieldInfo]
    is_auth: bool = False
    pk_field: str = "id"
    repository_name: str | None = None
    auth_identifier: str | None = None
    auth_providers: list[AuthProviderInfo] = field(default_factory=list)
    routes: dict[str, RouteInfo] = field(default_factory=dict)
    """First route serving each operation; identities also map `register` to their public create route."""
    pagination: IRPagination | None = None
    roles: RolesInfo | None = None
    access: dict[str, dict[str, str]] = field(default_factory=dict)
    """Per operation and principal column: `allow`, `deny` or `conditional`."""

    @property
    def operations(self) -> frozenset[str]:
        return frozenset(self.routes)

    @property
    def serves_login(self) -> bool:
        return "login" in self.routes

    @property
    def edit_operation(self) -> str | None:
        return next((op for op in ("update", "replace") if op in self.routes), None)

    @property
    def signup_fields(self) -> list[EntityFieldInfo]:
        """Writable fields a new identity fills in, identifier first; roles take their default."""
        excluded = {self.pk_field, self.roles.field if self.roles else None}
        writable = [f for f in self.fields.values() if not f.readonly and f.name not in excluded]
        return sorted(writable, key=lambda f: f.name != self.auth_identifier)


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
    session_delivery: str = "token-url"
