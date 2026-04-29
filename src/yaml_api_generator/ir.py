from dataclasses import asdict, dataclass, field
from typing import Any

from .when_ast import WhenExpr


# Well-known OIDC discovery URLs; provider name resolves automatically when listed here.
WELL_KNOWN_OIDC_DISCOVERY: dict[str, str] = {
    "google": "https://accounts.google.com/.well-known/openid-configuration",
    "microsoft": "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
    "apple": "https://appleid.apple.com/.well-known/openid-configuration",
}


@dataclass(frozen=True)
class IROIDCProvider:
    name: str
    client_id: str
    client_secret: str
    discovery_url: str
    type: str = "oidc"


@dataclass(frozen=True)
class IRSAMLProvider:
    name: str
    idp_metadata_url: str
    sp_entity_id: str
    type: str = "saml"


IRProvider = IROIDCProvider | IRSAMLProvider


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
class IRMongo:
    uri: str = "mongodb://localhost:27017"
    database: str = "yaml_api"


@dataclass(frozen=True)
class IRCollection:
    name: str
    entity_name: str
    type: str
    idField: str
    idFormat: str
    fields: dict[str, Any]
    operations: IROperations


@dataclass(frozen=True)
class IRDocumentBinding:
    collection: str
    id_param: str | None = None


@dataclass(frozen=True)
class IRAccessRule:
    principal: str
    required_role: str | None = None
    when: WhenExpr | None = None
    document: IRDocumentBinding | None = None
    effect: str = "allow"
    filter: str | None = None
    write_fields: list[str] = field(default_factory=list)
    reason: str | None = None


@dataclass(frozen=True)
class IRService:
    name: str
    repository: str | None = None
    operation: str | None = None
    handler: str | None = None


@dataclass(frozen=True)
class IRRoute:
    method: str
    path: str
    operation: str
    collection: str | None = None
    service: str | None = None
    is_public: bool = True
    access_rules: list[IRAccessRule] | None = None
    handler: str | None = None


@dataclass(frozen=True)
class IRProviderBinding:
    provider: str
    identifier: str
    claim_mapping: dict[str, str] = field(default_factory=dict)
    auto_provision: bool = True


@dataclass(frozen=True)
class IRIdentityCollection:
    name: str
    bindings: tuple[IRProviderBinding, ...]
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
    services: dict[str, IRService] = field(default_factory=dict)
    role_hierarchies: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    providers: dict[str, IRProvider] = field(default_factory=dict)
    mongo: IRMongo = field(default_factory=IRMongo)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
