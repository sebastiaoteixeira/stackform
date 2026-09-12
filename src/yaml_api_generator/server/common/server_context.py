from dataclasses import dataclass, field
from typing import Any

from yaml_api_generator.ir import (
    IRDocumentBinding,
    IRIdentityBinding,
    IRProviderBinding,
    IRRequestBinding,
    WhereRhs,
)
from yaml_api_generator.ir.api import IRPagination, IRRolesConfig
from yaml_api_generator.ir.when import WhenExpr


@dataclass(frozen=True)
class RuntimeCollectionDescriptor:
    name: str
    type: str
    id_field: str
    id_format: str
    fields: dict[str, Any]
    datastore: str | None = None


@dataclass(frozen=True)
class RuntimeOperationDescriptor:
    name: str
    query: dict | None = None
    handler: str | None = None


@dataclass(frozen=True)
class RuntimeIdentityDescriptor:
    name: str
    bindings: tuple[IRProviderBinding, ...]
    id_field: str
    roles: IRRolesConfig | None = None
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
class RuntimeAccessRule:
    principal: str
    required_role: str | None = None
    identity_symbols: dict[str, IRIdentityBinding] = field(default_factory=dict)
    document_symbols: dict[str, IRDocumentBinding] = field(default_factory=dict)
    request_symbols: dict[str, IRRequestBinding] = field(default_factory=dict)
    when: WhenExpr | None = None
    effect: str = "allow"
    reason: str | None = None
    bind: dict[str, WhereRhs] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeRouteDescriptor:
    method: str
    path: str
    operation: str
    collection: str | None
    is_public: bool
    handler: str | None = None
    access_rules: list[RuntimeAccessRule] | None = None
    service_input: dict[str, Any] | None = None
    service_forwarding: dict[str, Any] = field(default_factory=dict)
    pagination: IRPagination | None = None


@dataclass(frozen=True)
class RuntimeAuthConfig:
    enabled: bool
    identity_collections: dict[str, RuntimeIdentityDescriptor]
    identity_id_fields: dict[str, str]
    has_password_auth: bool
    has_api_key_auth: bool
    # Transitively expanded: collection_name -> role -> set of included roles
    role_hierarchies: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    providers: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeSessionConfig:
    algorithm: str = "HS256"
    ttl: int | None = None
    refresh: bool = False

    @property
    def uses_asymmetric(self) -> bool:
        return self.algorithm == "RS256"


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
    operations: dict[str, dict[str, RuntimeOperationDescriptor]] = field(default_factory=dict)
    spec_version: str = "0.2"
    session: RuntimeSessionConfig = field(default_factory=RuntimeSessionConfig)
