from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class IROperations:
    list: bool
    get: bool
    create: bool
    update: bool
    replace: bool
    delete: bool


@dataclass(frozen=True)
class IRApi:
    basePath: str
    version: str | None


@dataclass(frozen=True)
class IRCollection:
    name: str
    type: str
    idField: str
    idFormat: str
    fields: dict[str, Any]
    operations: IROperations


@dataclass(frozen=True)
class IRAccessRule:
    principal: str
    when: str | None = None
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
class IRIdentityCollection:
    name: str
    identifier: str | None
    via: list[str]


@dataclass(frozen=True)
class IRDocument:
    version: str
    api: IRApi
    collections: dict[str, IRCollection]
    routes: list[IRRoute]
    identityCollections: dict[str, IRIdentityCollection]
    services: dict[str, IRService] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
