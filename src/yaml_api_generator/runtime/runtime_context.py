from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeCollectionDescriptor:
    name: str
    type: str
    id_field: str
    id_format: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class RuntimeIdentityDescriptor:
    name: str
    identifier: str | None
    via: list[str]
    id_field: str


@dataclass(frozen=True)
class RuntimeRouteDescriptor:
    method: str
    path: str
    operation: str
    collection: str | None
    is_public: bool
    handler: str | None = None


@dataclass(frozen=True)
class RuntimeAuthConfig:
    enabled: bool
    identity_collections: dict[str, RuntimeIdentityDescriptor]
    identity_id_fields: dict[str, str]
    has_password_auth: bool
    has_api_key_auth: bool


@dataclass(frozen=True)
class RuntimeAppConfig:
    base_path: str
    api_version: str | None


@dataclass(frozen=True)
class RuntimeContext:
    app: RuntimeAppConfig
    collections: dict[str, RuntimeCollectionDescriptor]
    routes: list[RuntimeRouteDescriptor]
    auth: RuntimeAuthConfig
