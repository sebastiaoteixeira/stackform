"""Compilation context data structures for backend code generation.

Provides frozen dataclasses that represent the compiled context needed
to generate backend code. Bridges IR (intermediate representation) and
code generation by organizing data into generator-friendly structures.

Key types:
- CompileContext: Top-level context with all compilation metadata
- RouteDescriptor: HTTP route configuration
- ModelDescriptor: Request/response model definition
- AuthConfig: Authentication and authorization settings
- FieldDescriptor: Model field with type and constraints
"""

from dataclasses import dataclass, field
from typing import Any

from ...ir.api import IRProvider, IRProviderBinding, IRRolesConfig
from ...ir.when import WhenExpr


@dataclass(frozen=True)
class SettingField:
    """One field in the generated Settings class.

    env_name doubles as both the attribute name and the env var key
    (pydantic-settings maps them 1:1 when case_sensitive=False).
    A None default means the field is required (fail-fast at startup).
    """

    env_name: str
    python_type: str  # "str" | "int"
    default: str | None  # None -> required field
    secret: bool = False


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
    identity_symbols: list[str] = field(default_factory=list)
    document_symbols: list[str] = field(default_factory=list)
    when: WhenExpr | None = None
    effect: str = "allow"


@dataclass(frozen=True)
class RouteDescriptor:
    method: str
    path: str
    relative_path: str
    operation: str
    collection: str | None
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
    bindings: list[IRProviderBinding]
    id_field: str
    roles: IRRolesConfig | None = None
    roles_field: str | None = None
    issues_jwt: bool = False

    @property
    def has_password(self) -> bool:
        return any(b.provider == "password" for b in self.bindings)

    @property
    def has_api_key(self) -> bool:
        return any(b.provider == "apiKey" for b in self.bindings)

    @property
    def identifier(self) -> str | None:
        password_binding = self.get_binding("password")
        return password_binding.identifier if password_binding else None

    def get_binding(self, provider: str) -> "IRProviderBinding | None":
        return next((b for b in self.bindings if b.provider == provider), None)


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    identity_collections: list[IdentityCollectionDescriptor]
    has_password_auth: bool
    has_api_key_auth: bool
    has_oidc_auth: bool = False
    has_saml_auth: bool = False
    providers: dict[str, IRProvider] = field(default_factory=dict)
    role_hierarchies: dict[str, dict[str, set[str]]] = field(default_factory=dict)

    @property
    def uses_jwt(self) -> bool:
        """JWT helpers and JWT_SECRET are needed whenever tokens are minted.

        Password login, OIDC, and SAML callbacks all issue bearer JWTs that
        later requests present back for principal resolution.
        """
        return self.has_password_auth or self.has_oidc_auth or self.has_saml_auth


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
    repository_operations: dict[str, list[dict]] = field(default_factory=dict)
    datastores: dict[str, dict] = field(default_factory=dict)

    @property
    def datastore_types(self) -> set[str]:
        return {ds["type"] for ds in self.datastores.values()}

    def collection_datastore_type(self, collection: str) -> str:
        return self.collections.get(collection, {}).get("datastore_type", "mongodb")
