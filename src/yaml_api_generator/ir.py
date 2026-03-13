from dataclasses import asdict, dataclass
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
class IRRoute:
    method: str
    path: str
    operation: str
    collection: str
    is_public: bool = True


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
