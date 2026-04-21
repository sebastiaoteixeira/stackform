from dataclasses import dataclass, field
from typing import Any

from ..ir import IRProviderBinding
from ..when_ast import WhenExpr


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
    bindings: tuple[IRProviderBinding, ...]
    id_field: str
    roles_field: str | None = None

    @property
    def has_password(self) -> bool:
        return any(b.provider == "password" for b in self.bindings)

    @property
    def has_api_key(self) -> bool:
        return any(b.provider == "apiKey" for b in self.bindings)

    def get_binding(self, provider: str) -> "IRProviderBinding | None":
        return next((b for b in self.bindings if b.provider == provider), None)


@dataclass(frozen=True)
class RuntimeDocumentBinding:
    collection: str
    id_param: str | None = None


@dataclass(frozen=True)
class RuntimeAccessRule:
    principal: str
    required_role: str | None = None
    when: WhenExpr | None = None
    document: RuntimeDocumentBinding | None = None
    effect: str = "allow"


@dataclass(frozen=True)
class RuntimeRouteDescriptor:
    method: str
    path: str
    operation: str
    collection: str | None
    is_public: bool
    handler: str | None = None
    access_rules: list[RuntimeAccessRule] | None = None


@dataclass(frozen=True)
class RuntimeAuthConfig:
    enabled: bool
    identity_collections: dict[str, RuntimeIdentityDescriptor]
    identity_id_fields: dict[str, str]
    has_password_auth: bool
    has_api_key_auth: bool
    role_hierarchies: dict[str, dict[str, set[str]]] = field(default_factory=dict)


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
