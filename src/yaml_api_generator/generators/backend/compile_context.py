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

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ...ir.api import IRFileField, IRPagination, IRProvider, IRRolesConfig, IRService
from ...ir.when import WhenExpr
from ...utils.strings import to_py_identifier

FILE_REQUIREMENTS = ("python-multipart", "puremagic", "anyio")


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
    python_type: str
    default: str | None
    secret: bool = False
    generator: Callable[[], str] | None = None


@dataclass(frozen=True)
class FileStoreDescriptor(ABC):
    """A file datastore as the generated app builds it from its settings."""

    name: str

    runtime_module: ClassVar[str]
    store_class: ClassVar[str]
    requirements: ClassVar[tuple[str, ...]] = ()

    def env_name(self, key: str) -> str:
        return f"FILES_{to_py_identifier(self.name).upper()}_{key}"

    @property
    @abstractmethod
    def settings(self) -> tuple[SettingField, ...]: ...

    @property
    @abstractmethod
    def arguments(self) -> tuple[str, ...]: ...

    @property
    def constructor(self) -> str:
        return f"{self.store_class}({', '.join(self.arguments)})"


@dataclass(frozen=True)
class FilesystemStoreDescriptor(FileStoreDescriptor):
    path: str = ""

    runtime_module = "filesystem_store"
    store_class = "FilesystemStore"

    @property
    def settings(self) -> tuple[SettingField, ...]:
        return (SettingField(self.env_name("PATH"), "str", self.path),)

    @property
    def arguments(self) -> tuple[str, ...]:
        return (f"settings.{self.env_name('PATH')}",)


@dataclass(frozen=True)
class S3StoreDescriptor(FileStoreDescriptor):
    bucket: str = ""
    endpoint: str | None = None
    region: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    prefix: str = ""
    local: bool = False

    runtime_module = "s3_store"
    store_class = "S3Store"
    requirements = ("aiobotocore",)

    @property
    def settings(self) -> tuple[SettingField, ...]:
        return (
            SettingField(self.env_name("BUCKET"), "str", self.bucket),
            SettingField(self.env_name("ENDPOINT"), "str", self.endpoint or ""),
            SettingField(self.env_name("REGION"), "str", self.region or ""),
            SettingField(self.env_name("PREFIX"), "str", self.prefix),
            self._credential("ACCESS_KEY", self.access_key),
            self._credential("SECRET_KEY", self.secret_key),
            SettingField(self.env_name("CREATE_BUCKET"), "bool", str(self.local)),
        )

    @property
    def arguments(self) -> tuple[str, ...]:
        value = lambda key: f"settings.{self.env_name(key)}"
        secret = lambda key: f"{value(key)}.get_secret_value() or None"
        return (
            value("BUCKET"),
            f"endpoint={value('ENDPOINT')} or None",
            f"region={value('REGION')} or None",
            f"access_key={secret('ACCESS_KEY')}",
            f"secret_key={secret('SECRET_KEY')}",
            f"prefix={value('PREFIX')}",
            f"create_bucket={value('CREATE_BUCKET')}",
        )

    def _credential(self, key: str, value: str | None) -> SettingField:
        """Credentials stay out of settings.py: only the generated env file carries the spec value."""
        return SettingField(
            self.env_name(key), "str", None, secret=True, generator=lambda: value or ""
        )


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
    name: str
    collection: str
    id_param: str | None = None
    where: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def uses_where(self) -> bool:
        return bool(self.where)


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
    document_bindings: list[DocumentBindingDescriptor] = field(default_factory=list)
    request_symbols: list[RequestSymbolDescriptor] = field(default_factory=list)
    when: WhenExpr | None = None
    effect: str = "allow"
    reason: str | None = None
    bind: dict[str, dict[str, Any]] = field(default_factory=dict)


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
    record_id_param: str | None = None
    record_parent_params: list[str] = field(default_factory=list)
    id_field: str | None = None
    service_input: dict[str, Any] = field(default_factory=dict)
    service_forwarding: dict[str, dict[str, Any]] = field(default_factory=dict)
    pagination: IRPagination | None = None

    @property
    def request_symbols(self) -> list[RequestSymbolDescriptor]:
        seen: dict[str, RequestSymbolDescriptor] = {}
        for rule in self.access_rules or ():
            for sym in rule.request_symbols:
                seen.setdefault(sym.name, sym)
        return list(seen.values())

    @property
    def where_collections(self) -> list[str]:
        return list(dict.fromkeys(
            binding.collection
            for rule in self.access_rules or ()
            for binding in rule.document_bindings
            if binding.uses_where
        ))

    @property
    def record_criteria(self) -> list[tuple[str, str]]:
        parents = [(name, name) for name in self.record_parent_params]
        if self.record_id_param is None or self.id_field is None:
            return parents
        return [*parents, (self.id_field, self.record_id_param)]

    @property
    def django_path(self) -> str:
        path = self.relative_path.lstrip("/")
        return re.sub(r"\{(\w+)\}", r"<str:\1>", path)


@dataclass(frozen=True)
class FileRouteDescriptor:
    """A derived file endpoint; `source` is the record route whose access it reuses."""

    action: str
    method: str
    relative_path: str
    collection: str
    field: IRFileField
    item: bool
    source: RouteDescriptor

    @property
    def handler_name(self) -> str:
        suffix = "_item" if self.item else ""
        return f"{self.action}_{self.collection}_{to_py_identifier(self.field.name)}{suffix}"


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
class SessionConfig:
    algorithm: str = "HS256"
    ttl: int | None = None
    refresh: bool = False
    delivery: str = "token-url"

    @property
    def uses_asymmetric(self) -> bool:
        return self.algorithm == "RS256"

    @property
    def uses_cookie(self) -> bool:
        return self.delivery == "cookie"


@dataclass(frozen=True)
class AppConfig:
    base_path: str
    api_version: str | None
    cors: CorsConfig | None = None
    port: int = 8000
    security_headers: bool = True


@dataclass(frozen=True)
class CompileContext:
    app: AppConfig
    models: list[ModelDescriptor]
    routes: list[RouteDescriptor]
    auth: AuthConfig
    collections: dict[str, Any]
    session: SessionConfig = field(default_factory=SessionConfig)
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
    vendored_requirements: tuple[str, ...] = ()
    sql_schema_managed: bool = False
    mongo_schema_managed: bool = False
    # File datastores referenced by at least one collection with file fields.
    file_stores: dict[str, FileStoreDescriptor] = field(default_factory=dict)
    # Collection name -> its file fields, only for collections that have any.
    file_fields: dict[str, dict[str, IRFileField]] = field(default_factory=dict)
    file_routes: list[FileRouteDescriptor] = field(default_factory=list)

    @property
    def has_files(self) -> bool:
        return bool(self.file_fields)

    @property
    def file_requirements(self) -> tuple[str, ...]:
        store_requirements = (req for store in self.file_stores.values() for req in store.requirements)
        return tuple(dict.fromkeys((*FILE_REQUIREMENTS, *store_requirements))) if self.has_files else ()

    @property
    def file_runtime_modules(self) -> tuple[str, ...]:
        store_modules = (store.runtime_module for store in self.file_stores.values())
        return tuple(dict.fromkeys(("files", "multipart", "file_requests", *store_modules))) if self.has_files else ()

    @property
    def datastore_types(self) -> set[str]:
        return {ds["type"] for ds in self.datastores.values()}

    @property
    def mongo_unique_indexes(self) -> dict[str, list[str]]:
        return {
            name: [
                field_name
                for field_name, field in collection["fields"].items()
                if isinstance(field, dict) and field.get("unique")
            ]
            for name, collection in self.collections.items()
            if collection["datastore_type"] in {"mongodb", "mongo"}
            and any(
                isinstance(field, dict) and field.get("unique")
                for field in collection["fields"].values()
            )
        }

    def collection_datastore_type(self, collection: str) -> str:
        return self.collections.get(collection, {}).get("datastore_type", "mongodb")
