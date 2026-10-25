"""Sign provider-authenticated users into identity collections through the shared runtime."""

from dataclasses import asdict, dataclass
from typing import Any

from yaml_api_generator.ir.api import IRProviderBinding
from yaml_api_generator.runtime.provisioning import ProviderBinding, ProviderRelation, RecordsOf, SignInRefused
from ..repositories import BaseRepository, ConflictError, RepositoryRegistry
from ..server_context import RuntimeCollectionDescriptor
from ..utils.ids import generate_id

# A sign-in these raise is refused with 401, never left to fail the request
REFUSALS = (SignInRefused, ConflictError)


def provider_binding(binding: IRProviderBinding) -> ProviderBinding:
    values = asdict(binding)
    relations = {fk: ProviderRelation(**relation) for fk, relation in values["relations"].items()}
    return ProviderBinding(**{**values, "relations": relations})


@dataclass(frozen=True)
class CollectionRecords:
    """One collection of a dev-server repository, seen as runtime ``Records``."""

    repository: BaseRepository
    collection: RuntimeCollectionDescriptor

    async def find_one(self, criteria: dict[str, Any]) -> dict[str, Any] | None:
        return await self.repository.find_one(self.collection.name, criteria)

    async def update_by(self, criteria: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
        return await self.repository.update_by(self.collection.name, criteria, data)

    async def upsert_by(self, key_field: str, data: dict[str, Any]) -> dict[str, Any]:
        id_field = self.collection.id_field
        identity = {} if id_field in data else {id_field: generate_id(self.collection.id_format)}
        return await self.repository.upsert_by(self.collection.name, key_field, {**identity, **data})


def records_of(
    registry: RepositoryRegistry, collections: dict[str, RuntimeCollectionDescriptor]
) -> RecordsOf:
    return lambda name: CollectionRecords(registry.for_collection(name), collections[name])
