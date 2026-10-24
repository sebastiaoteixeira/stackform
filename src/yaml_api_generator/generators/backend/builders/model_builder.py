"""Payload model descriptors for backend code generation.

Each collection gets one ``<Collection>Fields`` model holding its writable
fields; the create and replace payloads extend it and the update payload is
its partial form, so no field is declared twice. A DTO is its own base and
gets the same partial update form.
"""

from yaml_api_generator.ir import (
    CRUD_OPERATIONS,
    IRCollection,
    IRDto,
    IRIdentityCollection,
    IRRepository,
    SECRET_FIELD,
    payload_fields,
)
from yaml_api_generator.utils.strings import to_pascal_case
from ..compile_context import FieldDescriptor, ModelDescriptor


WRITE_OPERATIONS = ("create", "update", "replace")
_PASSWORD = FieldDescriptor("password", SECRET_FIELD)


def payload_name(owner: str, operation: str) -> str:
    """``<Owner>Fields`` for the shared base, else ``<Owner><Operation>Payload``."""
    suffix = "Fields" if operation == "fields" else f"{operation.capitalize()}Payload"
    return f"{to_pascal_case(owner)}{suffix}"


def dto_payload_name(dto: str, operation: str) -> str:
    """The model a route typed by ``dto`` validates its ``operation`` body with."""
    return payload_name(dto, "update") if operation == "update" else to_pascal_case(dto)


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
            for model in self._family(col, identity_map.get(name), repositories.get(name))
        ]

    def build_dto_models(self, dtos: dict[str, IRDto]) -> list[ModelDescriptor]:
        return [
            model
            for dto in dtos.values()
            for model in (
                ModelDescriptor(
                    name=dto_payload_name(dto.name, "dto"),
                    collection=dto.name,
                    operation="dto",
                    fields=_descriptors(payload_fields(dto.fields)),
                ),
                ModelDescriptor(
                    name=dto_payload_name(dto.name, "update"),
                    collection=dto.name,
                    operation="update",
                    fields=[],
                    base=dto_payload_name(dto.name, "dto"),
                ),
            )
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
                fields=_descriptors(payload_fields(col.fields, col.files.keys())),
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
