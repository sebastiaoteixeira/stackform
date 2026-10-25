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


@dataclass(frozen=True)
class EntityFieldInfo:
    """One entity field with its spec config, which the UI reads as the API validates it."""

    name: str
    config: dict[str, Any]
    roles_of: str | None = None
    """The identity whose roles this field stores, when it is that identity's roles field."""

    @property
    def type(self) -> str:
        return self.config.get("type", "string")

    @property
    def required(self) -> bool:
        return self.config.get("required", False)

    @property
    def unique(self) -> bool:
        return self.config.get("unique", False)

    @property
    def enum_values(self) -> list[str] | None:
        return self.config.get("values")

    @property
    def ref_entity(self) -> str | None:
        return self.config.get("ref")

    @property
    def default(self) -> Any:
        return self.config.get("default")

    @property
    def readonly(self) -> bool:
        return self.config.get("readonly", False)


PASSWORD_FIELD = EntityFieldInfo("password", {"type": "string", "format": "password", "required": True})

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
class AccessColumn:
    """A signed-in principal of the access matrix: an identity, holding `role` when that identity has roles."""

    identity: str
    collection: str
    role: str | None
    held_roles: frozenset[str]


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
    def serves_register(self) -> bool:
        return "register" in self.routes

    @property
    def edit_operation(self) -> str | None:
        return next((op for op in ("update", "replace") if op in self.routes), None)

    @property
    def writable_fields(self) -> list[EntityFieldInfo]:
        return [f for f in self.fields.values() if not f.readonly]

    @property
    def credential_fields(self) -> list[EntityFieldInfo]:
        """What a password identity sends only when it is created, besides its fields."""
        return [PASSWORD_FIELD] if self.auth_identifier else []

    @property
    def signup_fields(self) -> list[EntityFieldInfo]:
        """Writable fields a new identity fills in, identifier first, then its credentials; roles take their default."""
        excluded = {self.pk_field, self.roles.field if self.roles else None}
        writable = [f for f in self.writable_fields if f.name not in excluded]
        return sorted(writable, key=lambda f: f.name != self.auth_identifier) + self.credential_fields


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
    access_columns: dict[str, AccessColumn | None] = field(default_factory=dict)
    """The columns of every entity's access verdicts; anonymous callers are the `None` column."""
    session_delivery: str = "token-url"

    @property
    def account_entity(self) -> EntityInfo | None:
        """The identity the sign-in page serves: one that logs in, else one that registers."""
        return min(
            (entity for entity in self.entities.values() if entity.serves_login or entity.serves_register),
            key=lambda entity: not entity.serves_login,
            default=None,
        )
