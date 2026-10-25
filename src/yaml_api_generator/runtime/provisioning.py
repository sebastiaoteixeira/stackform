"""Sign an externally authenticated user into the local record of an identity collection."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .claims import claim_value, resolve_claim_path


class SignInRefused(Exception):
    """The claims cannot sign anyone into the identity collection."""


class Records(Protocol):
    """The record operations sign-in needs from one collection."""

    async def find_one(self, criteria: dict[str, Any]) -> dict[str, Any] | None: ...

    async def update_by(self, criteria: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None: ...

    async def upsert_by(self, key_field: str, data: dict[str, Any]) -> dict[str, Any]: ...


RecordsOf = Callable[[str], Records]


@dataclass(frozen=True)
class ProviderRelation:
    """A foreign key filled with the id of the ``collection`` record whose fields match the claims."""

    collection: str
    match: Mapping[str, str] = field(default_factory=dict)
    id_field: str = "id"
    match_types: Mapping[str, str] = field(default_factory=dict)

    async def resolve(self, claims: dict[str, Any], records: RecordsOf) -> Any | None:
        criteria = {
            target: claim_value(resolve_claim_path(claims, path), self.match_types.get(target))
            for target, path in self.match.items()
        }
        if None in criteria.values():
            return None
        record = await records(self.collection).find_one(criteria)
        return record.get(self.id_field) if record is not None else None


@dataclass(frozen=True)
class ProviderBinding:
    """How one provider's claims fill the fields of an identity record."""

    provider: str
    identifier: str
    claim_mapping: Mapping[str, str] = field(default_factory=dict)
    auto_provision: bool = True
    relations: Mapping[str, ProviderRelation] = field(default_factory=dict)
    field_types: Mapping[str, str] = field(default_factory=dict)

    def mapped_fields(self, claims: dict[str, Any]) -> dict[str, Any]:
        """The claimed values of the identity fields; a value its field cannot hold stays unclaimed."""
        claimed = {local: resolve_claim_path(claims, path) for local, path in self.claim_mapping.items()}
        if claimed.get(self.identifier) is None:
            claimed[self.identifier] = claims.get("email") or claims.get("login") or claims.get("sub")
        fitted = {local: claim_value(value, self.field_types.get(local)) for local, value in claimed.items()}
        return {local: value for local, value in fitted.items() if value is not None}

    async def sign_in(
        self,
        claims: dict[str, Any],
        records: RecordsOf,
        collection: str,
        subject_field: str | None = None,
    ) -> dict[str, Any] | None:
        """The record keyed by the identifier, or by ``subject_field`` holding the token subject.

        Every sign-in brings mapped fields and relations up to date; the record id never changes.
        """
        fields = self.mapped_fields(claims)
        if self.identifier not in fields:
            raise SignInRefused(f"The provider's claims carry no usable '{self.identifier}'")
        fields |= {fk: await relation.resolve(claims, records) for fk, relation in self.relations.items()}
        if subject_field is not None:
            fields[subject_field] = str(claims["sub"])
        key_field = subject_field or self.identifier
        key = {key_field: fields[key_field]}
        identities = records(collection)
        existing = await identities.find_one(key)
        if existing is None:
            return await identities.upsert_by(key_field, fields) if self.auto_provision else None
        changed = {name: value for name, value in fields.items() if existing.get(name) != value}
        return await identities.update_by(key, changed) if changed else existing
