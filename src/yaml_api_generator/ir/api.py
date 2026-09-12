"""Intermediate Representation (IR) for API specification.

Defines the complete IR structure representing a validated YAML API spec.
All IR types are frozen dataclasses for immutability and type safety.

Key structures:
- IRApi: Top-level API metadata (base path, version, CORS)
- IRCollection: Entity collection with fields and operations
- IRRoute: HTTP endpoint with authorization rules
- IRDocument: Complete parsed specification
- IRIdentityCollection: Authentication collection configuration
- IRProvider: OIDC/SAML authentication provider settings

Authorization:
- IRAccessRule: Role and condition-based access control
- WhenExpr: Authorization expression AST (imported from ir.when)

The IR serves as the single source of truth for code generation,
eliminating repeated YAML parsing and validation.
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .when import WhenExpr
from ..constants import CRUD_OPERATIONS


@dataclass(frozen=True)
class IROIDCProvider:
    name: str
    client_id: str
    type: str = "oidc"
    trust: str = "app"
    client_secret: str | None = None
    discovery_url: str | None = None
    issuer: str | None = None
    audiences: tuple[str, ...] = ()

    @property
    def is_idp(self) -> bool:
        return self.trust == "idp"


@dataclass(frozen=True)
class IRSAMLProvider:
    name: str
    type: str = "saml"
    trust: str = "app"
    idp_metadata_url: str | None = None
    sp_entity_id: str | None = None
    issuer: str | None = None
    audience: str | None = None

    @property
    def is_idp(self) -> bool:
        return self.trust == "idp"


IRProvider = IROIDCProvider | IRSAMLProvider


@dataclass(frozen=True)
class IRDeployDocker:
    image: str | None = None


@dataclass(frozen=True)
class IRDeploySystemd:
    user: str = "ubuntu"
    restart: str = "on-failure"


@dataclass(frozen=True)
class IRDeploy:
    runtime: str
    name: str | None = None
    port: int = 8000
    mongo_local: bool = False
    env_vars: tuple[str, ...] = field(default_factory=tuple)
    docker: IRDeployDocker | None = None
    systemd: IRDeploySystemd | None = None
    extra_services: tuple[tuple[str, dict], ...] = field(default_factory=tuple)
    include: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IRSortKey:
    field: str
    dir: str = "asc"


@dataclass(frozen=True)
class IRPageSize:
    default: int
    max: int


@dataclass(frozen=True)
class IRPagination:
    strategy: str
    size: IRPageSize
    count: str = "none"
    on_overflow: str = "clamp"
    envelope: bool = False
    sort: tuple[IRSortKey, ...] = ()


@dataclass(frozen=True)
class IROperation:
    name: str
    query: dict | None = None
    handler: str | None = None


@dataclass(frozen=True)
class IRRepository:
    name: str
    entity: str | None = None
    crud: tuple[str, ...] = CRUD_OPERATIONS
    operations: dict[str, IROperation] = field(default_factory=dict)
    datastore: str | None = None
    abstract: bool = False
    inherits: str | None = None


@dataclass(frozen=True)
class IROperations:
    list: bool
    get: bool
    create: bool
    update: bool
    replace: bool
    delete: bool


@dataclass(frozen=True)
class IRCors:
    origins: list[str] = field(default_factory=lambda: ["*"])
    methods: list[str] = field(default_factory=lambda: ["*"])
    headers: list[str] = field(default_factory=lambda: ["*"])
    credentials: bool = False


@dataclass(frozen=True)
class IRApi:
    basePath: str
    version: str | None
    cors: IRCors | None = None
    port: int = 8000


@dataclass(frozen=True)
class IRSession:
    algorithm: str = "HS256"
    ttl: int | None = None
    refresh: bool = False
    delivery: str = "token-url"

    @property
    def uses_asymmetric(self) -> bool:
        return self.algorithm == "RS256"


@dataclass(frozen=True)
class IRMongo:
    uri: str = "mongodb://localhost:27017"
    database: str = "yaml_api"
    type: str = "mongodb"


@dataclass(frozen=True)
class IRPostgres:
    dsn: str = "postgresql+asyncpg://localhost:5432/yaml_api"
    type: str = "postgres"


IRMongoDatastore = IRMongo
IRPostgresDatastore = IRPostgres
IRDatastore = IRMongo | IRPostgres


@dataclass(frozen=True)
class IRCollection:
    name: str
    entity_name: str
    type: str
    idField: str
    idFormat: str
    fields: dict[str, Any]
    datastore: str | None = None


@dataclass(frozen=True)
class IRSymbolRef:
    root: str
    path: tuple[str, ...] = ()


@dataclass(frozen=True)
class IRLiteralRef:
    value: Any


WhereRhs = IRSymbolRef | IRLiteralRef


@dataclass(frozen=True)
class IRWhereConjunct:
    field: str
    rhs: WhereRhs


@dataclass(frozen=True)
class IRDocumentBinding:
    collection: str
    id_param: str | None = None
    where: tuple[IRWhereConjunct, ...] = ()


@dataclass(frozen=True)
class IRIdentityBinding:
    entity_name: str
    collection_name: str


@dataclass(frozen=True)
class IRRequestBinding:
    part: str | None = None
    type_name: str | None = None
    raw: bool = False


IRBinding = IRIdentityBinding | IRDocumentBinding | IRRequestBinding


@dataclass(frozen=True)
class IRPolicy:
    name: str
    when: WhenExpr
    given: dict[str, IRBinding] = field(default_factory=dict)
    params: tuple[str, ...] = ()


@dataclass(frozen=True)
class IRDto:
    name: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class IRVendoredImport:
    alias: str
    package: str
    source: Path
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class IRAccessRule:
    principal: str
    required_role: str | None = None
    identity_symbols: dict[str, IRIdentityBinding] = field(default_factory=dict)
    document_symbols: dict[str, IRDocumentBinding] = field(default_factory=dict)
    request_symbols: dict[str, IRRequestBinding] = field(default_factory=dict)
    when: WhenExpr | None = None
    effect: str = "allow"
    filter: str | None = None
    write_fields: list[str] = field(default_factory=list)
    reason: str | None = None
    bind: dict[str, WhereRhs] = field(default_factory=dict)


@dataclass(frozen=True)
class IRServiceInput:
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self.fields)


@dataclass(frozen=True)
class IRService:
    name: str
    repository: str | None = None
    operation: str | None = None
    handler: str | None = None
    abstract: bool = False
    inherits: str | None = None
    input: IRServiceInput | None = None
    forwarding: dict[str, WhereRhs] = field(default_factory=dict)


@dataclass(frozen=True)
class IRRoute:
    method: str
    path: str
    operation: str
    collection: str | None = None   # DEPRECATED: Routes don't have collections. They'r independent concepts
    service: str | None = None
    is_public: bool = True
    access_rules: list[IRAccessRule] | None = None
    handler: str | None = None
    pagination: IRPagination | None = None


@dataclass(frozen=True)
class IRRolesConfig:
    values: tuple[str, ...]
    default: str
    hierarchy: dict[str, tuple[str, ...]] = field(default_factory=dict)


class RoleHierarchyCycleError(ValueError):
    """Raised when a role hierarchy contains a cycle (or self-inclusion)."""

    def __init__(self, role: str) -> None:
        super().__init__(f"role hierarchy contains a cycle through '{role}'")
        self.role = role


def flatten_role_hierarchy(
    hierarchy: dict[str, Iterable[str]],
) -> dict[str, set[str]]:
    """Transitively expand role inclusions.

    Given {admin: [moderator], moderator: [user]},
    produces {admin: {moderator, user}, moderator: {user}}.

    Raises RoleHierarchyCycleError if the inclusions form a cycle.
    """
    flattened: dict[str, set[str]] = {}
    in_progress: set[str] = set()

    def _expand(role: str) -> set[str]:
        if role in flattened:
            return flattened[role]
        if role in in_progress:
            raise RoleHierarchyCycleError(role)
        in_progress.add(role)
        result: set[str] = set()
        for included in hierarchy.get(role, ()):
            result.add(included)
            result |= _expand(included)
        in_progress.discard(role)
        flattened[role] = result
        return result

    for role in hierarchy:
        _expand(role)

    return flattened


@dataclass(frozen=True)
class IRProviderRelation:
    collection: str
    match: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IRProviderBinding:
    provider: str
    identifier: str
    claim_mapping: dict[str, str] = field(default_factory=dict)
    auto_provision: bool = True
    relations: dict[str, IRProviderRelation] = field(default_factory=dict)


@dataclass(frozen=True)
class IRIdentityCollection:
    name: str
    bindings: tuple[IRProviderBinding, ...]
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
class IRDocument:
    version: str
    api: IRApi
    collections: dict[str, IRCollection]
    routes: list[IRRoute]
    identityCollections: dict[str, IRIdentityCollection]
    dtos: dict[str, IRDto] = field(default_factory=dict)
    services: dict[str, IRService] = field(default_factory=dict)
    role_hierarchies: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    providers: dict[str, IRProvider] = field(default_factory=dict)
    mongo: IRMongo = field(default_factory=IRMongo)
    datastores: dict[str, IRDatastore] = field(default_factory=dict)
    default_datastore: str = "default"
    deploy: IRDeploy | None = None
    repositories: dict[str, IRRepository] = field(default_factory=dict)
    policies: dict[str, IRPolicy] = field(default_factory=dict)
    session: IRSession = field(default_factory=IRSession)
    ui_config: dict[str, Any] | None = None
    vendored_imports: tuple[IRVendoredImport, ...] = ()
    vendored_requirements: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def has_ui(self) -> bool:
        return self.ui_config is not None
