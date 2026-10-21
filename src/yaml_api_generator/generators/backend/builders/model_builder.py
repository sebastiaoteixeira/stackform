"""Payload model descriptors for backend code generation.

Each collection gets one ``<Collection>Fields`` model holding its writable
fields; the create and replace payloads extend it and the update payload is
its partial form, so no field is declared twice.
"""

from yaml_api_generator.ir import (
    CRUD_OPERATIONS,
    IRCollection,
    IRDto,
    IRIdentityCollection,
    IRRepository,
    SECRET_FIELD,
    writable_fields,
)
from yaml_api_generator.utils.strings import to_pascal_case
from ..compile_context import FieldDescriptor, ModelDescriptor


WRITE_OPERATIONS = ("create", "update", "replace")
_PASSWORD = FieldDescriptor("password", SECRET_FIELD)


def payload_name(collection: str, operation: str) -> str:
    """``<Collection>Fields`` for the shared base, else ``<Collection><Operation>Payload``."""
    prefix = "".join(part.capitalize() for part in collection.split("_"))
    return f"{prefix}Fields" if operation == "fields" else f"{prefix}{operation.capitalize()}Payload"


def _descriptors(fields: dict[str, dict]) -> list[FieldDescriptor]:
    return [FieldDescriptor(name, config) for name, config in fields.items()]


class ModelBuilder:
    """Builds payload model descriptors from IR collections and DTOs."""

    def build_models(
        self,
        collections: dict[str, IRCollection],
        identity_map: dict[str, IRIdentityCollection],
        repositories: dict[str, IRRepository],
    ) -> list[ModelDescriptor]:
        return [
            model
            for name, col in collections.items()
            for model in self._family(
                col, identity_map.get(name), repositories.get(name)
            )
        ]

    def build_dto_models(self, dtos: dict[str, IRDto]) -> list[ModelDescriptor]:
        return [
            ModelDescriptor(
                name=to_pascal_case(dto.name),
                collection=dto.name,
                operation="dto",
                fields=_descriptors(writable_fields(dto.fields)),
            )
            for dto in dtos.values()
        ]

    def _family(
        self,
        col: IRCollection,
        identity: IRIdentityCollection | None,
        repo: IRRepository | None,
    ) -> list[ModelDescriptor]:
        enabled = repo.crud if repo is not None else CRUD_OPERATIONS
        operations = [op for op in WRITE_OPERATIONS if op in enabled]
        if not operations:
            return []
        base = payload_name(col.name, "fields")
        own_fields = {
            "create": [_PASSWORD] if identity is not None and identity.has_password else [],
        }
        return [
            ModelDescriptor(
                name=base,
                collection=col.name,
                operation="fields",
                fields=_descriptors(writable_fields(col.fields, col.files.keys())),
            ),
            *(
                ModelDescriptor(
                    name=payload_name(col.name, op),
                    collection=col.name,
                    operation=op,
                    fields=own_fields.get(op, []),
                    base=base,
                )
                for op in operations
            ),
        ]
