from dataclasses import dataclass, field
from typing import Any


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
class RouteDescriptor:
    method: str
    path: str
    operation: str
    collection: str
    id_field: str
    id_format: str
    is_public: bool
    needs_auth: bool
    is_identity_create: bool
    body_model: str | None
    has_id_param: bool
    password_via: bool


@dataclass(frozen=True)
class IdentityCollectionDescriptor:
    name: str
    identifier: str | None
    via: list[str]
    id_field: str


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    identity_collections: list[IdentityCollectionDescriptor]
    has_password_auth: bool
    has_api_key_auth: bool


@dataclass(frozen=True)
class AppConfig:
    base_path: str
    api_version: str | None


@dataclass(frozen=True)
class CompileContext:
    app: AppConfig
    models: list[ModelDescriptor]
    routes: list[RouteDescriptor]
    auth: AuthConfig
    collections: dict[str, Any]
