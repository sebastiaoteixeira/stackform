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

from ...ir.api import IRProvider, IRRolesConfig, IRService
from ...ir.when import WhenExpr


@dataclass(frozen=True)
class ProviderRelationDescriptor:
    fk_field: str
    collection: str
    id_field: str
    match: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "fk_field": self.fk_field,
            "collection": self.collection,
            "id_field": self.id_field,
            "match": self.match,
        }


@dataclass(frozen=True)
class ProviderBindingDescriptor:
    provider: str
    identifier: str
    claim_mapping: dict[str, str]
    auto_provision: bool
    relations: list[ProviderRelationDescriptor]

    @property
    def relations_data(self) -> list[dict[str, Any]]:
        return [r.as_dict() for r in self.relations]


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
    generated: bool = False


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


_OPENAPI_PARTS = ("body", "path", "query", "header", "cookie")


@dataclass(frozen=True)
class RequestSymbolDescriptor:
    name: str
    part: str | None
    type_name: str | None = None
    raw: bool = False

    @property
    def is_whole(self) -> bool:
        return self.part is None and self.raw

    @property
    def effective_part(self) -> str:
        return self.part or "body"

    @property
    def is_record_shaped(self) -> bool:
        return not self.is_whole

    def binds(self, part: str) -> bool:
        return self.is_whole or self.effective_part == part


@dataclass(frozen=True)
class AccessRuleDescriptor:
    principal: str
    required_role: str | None = None
    identity_symbols: list[str] = field(default_factory=list)
    document_symbols: list[str] = field(default_factory=list)
    request_symbols: list[RequestSymbolDescriptor] = field(default_factory=list)
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
    path_params: list[str] = field(default_factory=list)
    needs_request: bool = False
    typed_body_model: str | None = None
    # IR service name (expanded flat key, e.g. "list-posts") backing this route.
    service: str | None = None

    @property
    def request_symbols(self) -> list[RequestSymbolDescriptor]:
        seen: dict[str, RequestSymbolDescriptor] = {}
        for rule in self.access_rules or ():
            for sym in rule.request_symbols:
                seen.setdefault(sym.name, sym)
        return list(seen.values())


@dataclass(frozen=True)
class IdentityCollectionDescriptor:
    name: str
    bindings: list[ProviderBindingDescriptor]
    id_field: str
    roles: IRRolesConfig | None = None
    roles_field: str | None = None
    issues_jwt: bool = False
    datastore_type: str = "mongodb"
    id_format: str = "uuidv7"

    @property
    def is_sql(self) -> bool:
        return self.datastore_type in ("postgres", "postgresql")

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

    def get_binding(self, provider: str) -> "ProviderBindingDescriptor | None":
        return next((b for b in self.bindings if b.provider == provider), None)


@dataclass(frozen=True)
class IdpProviderDescriptor:
    """Metadata for a trust: idp OIDC provider baked into the generated backend."""

    name: str
    discovery_url: str
    client_id: str
    issuer: str | None = None
    audiences: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    identity_collections: list[IdentityCollectionDescriptor]
    has_password_auth: bool
    has_api_key_auth: bool
    has_oidc_auth: bool = False
    has_saml_auth: bool = False
    has_idp_auth: bool = False
    has_app_oidc_auth: bool = False
    idp_providers: list[IdpProviderDescriptor] = field(default_factory=list)
    providers: dict[str, IRProvider] = field(default_factory=dict)
    role_hierarchies: dict[str, dict[str, set[str]]] = field(default_factory=dict)

    @property
    def uses_jwt(self) -> bool:
        """JWT helpers and JWT_SECRET are needed whenever the app mints its own tokens.

        Password login and app-trust OIDC/SAML callbacks issue bearer JWTs.
        Pure idp-trust providers never mint a session token.
        """
        return self.has_password_auth or self.has_app_oidc_auth or self.has_saml_auth


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
    # Abstract base repositories (which declare operations) rendered as
    # inheritable classes: name -> datastore type. Their operations live in
    # repository_operations.
    repository_abstract: dict[str, str] = field(default_factory=dict)
    # Concrete repo (collection) name -> abstract base repo name it inherits.
    repository_inherits: dict[str, str] = field(default_factory=dict)
    # IR services keyed by their expanded flat name (e.g. "list-posts").
    services: dict[str, IRService] = field(default_factory=dict)
    dto_models: list[ModelDescriptor] = field(default_factory=list)

    @property
    def datastore_types(self) -> set[str]:
        return {ds["type"] for ds in self.datastores.values()}

    def collection_datastore_type(self, collection: str) -> str:
        return self.collections.get(collection, {}).get("datastore_type", "mongodb")
