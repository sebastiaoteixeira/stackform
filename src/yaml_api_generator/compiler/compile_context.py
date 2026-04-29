from dataclasses import dataclass, field
from typing import Any

from ..when_ast import WhenExpr


@dataclass(frozen=True)
class FieldDescriptor:
    name: str
    type: str
    required: bool
    is_optional: bool
    default: Any | None = None
    constraints: dict[str, Any] = field(default_factory=dict)
    enum_values: list[str] | None = None
    array_item_type: str | None = None
    ref_collection: str | None = None


@dataclass(frozen=True)
class ModelDescriptor:
    name: str
    collection: str
    operation: str
    fields: list[FieldDescriptor]


@dataclass(frozen=True)
class DocumentBindingDescriptor:
    collection: str
    id_param: str | None = None


@dataclass(frozen=True)
class AccessRuleDescriptor:
    principal: str
    required_role: str | None = None
    when: WhenExpr | None = None
    effect: str = "allow"


@dataclass(frozen=True)
class RouteDescriptor:
    method: str
    path: str
    operation: str
    collection: str | None
    id_field: str | None
    id_format: str | None
    is_public: bool
    needs_auth: bool
    is_identity_create: bool
    body_model: str | None
    has_id_param: bool
    password_via: bool
    handler: str | None = None
    access_rules: list[AccessRuleDescriptor] | None = None


@dataclass(frozen=True)
class IdentityCollectionDescriptor:
    name: str
    identifier: str | None
    via: list[str]
    id_field: str
    roles_field: str | None = None


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    identity_collections: list[IdentityCollectionDescriptor]
    has_password_auth: bool
    has_api_key_auth: bool


@dataclass(frozen=True)
class CorsConfig:
    origins: list[str] = field(default_factory=lambda: ["*"])
    methods: list[str] = field(default_factory=lambda: ["*"])
    headers: list[str] = field(default_factory=lambda: ["*"])
    credentials: bool = False


@dataclass(frozen=True)
class AppConfig:
    base_path: str
    api_version: str | None
    cors: CorsConfig | None = None
    port: int = 8000


@dataclass(frozen=True)
class CompileContext:
    app: AppConfig
    models: list[ModelDescriptor]
    routes: list[RouteDescriptor]
    auth: AuthConfig
    collections: dict[str, Any]
    role_hierarchies: dict[str, dict[str, list[str]]] = field(default_factory=dict)
