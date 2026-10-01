"""Model and field building for backend code generation.

Converts IR collections into Pydantic model descriptors with field validation.
"""

from collections.abc import Collection
from typing import Any

from yaml_api_generator.ir import CRUD_OPERATIONS, IRCollection, IRDto, IRIdentityCollection, IRRepository
from yaml_api_generator.utils.strings import to_pascal_case
from ..compile_context import FieldDescriptor, ModelDescriptor


WRITE_OPERATIONS = ("create", "update", "replace")


class ModelBuilder:
    """Builds Pydantic model descriptors from IR collections."""

    def build_models(
        self,
        collections: dict[str, IRCollection],
        identity_map: dict[str, IRIdentityCollection],
        repositories: dict[str, IRRepository],
    ) -> list[ModelDescriptor]:
        """Build model descriptors for write operations.

        Args:
            collections: Collection IR objects
            identity_map: Identity collection IR objects
            repositories: Repository IR objects

        Returns:
            List of model descriptors
        """
        models: list[ModelDescriptor] = []
        for name, col in collections.items():
            identity = identity_map.get(name)
            repo = repositories.get(name)
            enabled_ops = repo.crud if repo is not None else CRUD_OPERATIONS
            for op in WRITE_OPERATIONS:
                if op not in enabled_ops:
                    continue
                fields = self.build_fields(col, op, identity, excluded=col.files.keys())
                model_name = self._model_name(name, op)
                models.append(
                    ModelDescriptor(
                        name=model_name,
                        collection=name,
                        operation=op,
                        fields=fields,
                    )
                )

        return models

    def build_dto_models(self, dtos: dict[str, IRDto]) -> list[ModelDescriptor]:
        return [
            ModelDescriptor(
                name=to_pascal_case(dto.name),
                collection=dto.name,
                operation="dto",
                fields=self.build_fields(dto, "dto", None),
            )
            for dto in dtos.values()
        ]

    def build_fields(
        self,
        col: IRCollection,
        operation: str,
        identity: IRIdentityCollection | None,
        excluded: Collection[str] = (),
    ) -> list[FieldDescriptor]:
        """Build field descriptors for a model.

        Args:
            col: Collection IR object
            operation: Operation name (create, update, replace)
            identity: Identity collection IR object if collection is auth
            excluded: Field names kept out of the model (file fields travel outside the JSON payload)

        Returns:
            List of field descriptors
        """
        make_optional = operation == "update"
        fields: list[FieldDescriptor] = []

        for field_name, raw_config in col.fields.items():
            if not isinstance(raw_config, dict):
                continue
            if raw_config.get("type") == "id":
                continue
            if field_name == "_auth" or field_name in excluded:
                continue
            if raw_config.get("readonly", False):
                continue

            field_type = raw_config.get("type", "string")
            required = bool(raw_config.get("required", False))
            has_default = "default" in raw_config
            default_value: Any = None

            if make_optional:
                is_optional = True
                default_value = raw_config.get("default")
            elif has_default:
                is_optional = False
                default_value = raw_config["default"]
            elif required:
                is_optional = False
                default_value = None
            else:
                is_optional = True
                default_value = None

            constraints: dict[str, Any] = {}
            if raw_config.get("min") is not None:
                constraints["min"] = raw_config["min"]
            if raw_config.get("max") is not None:
                constraints["max"] = raw_config["max"]
            if raw_config.get("minLength") is not None:
                constraints["min_length"] = raw_config["minLength"]
            if raw_config.get("maxLength") is not None:
                constraints["max_length"] = raw_config["maxLength"]
            if raw_config.get("format") is not None:
                constraints["format"] = raw_config["format"]

            enum_values = raw_config.get("values") if field_type == "enum" else None
            array_item_type = None
            if field_type == "array":
                items = raw_config.get("items")
                if isinstance(items, dict):
                    array_item_type = items.get("type", "string")

            ref_collection = raw_config.get("ref") if field_type == "ref" else None

            fields.append(
                FieldDescriptor(
                    name=field_name,
                    type=field_type,
                    required=required and not make_optional,
                    is_optional=is_optional,
                    default=default_value,
                    constraints=constraints,
                    enum_values=enum_values,
                    array_item_type=array_item_type,
                    ref_collection=ref_collection,
                )
            )

        if identity is not None and operation == "create" and identity.has_password:
            has_password_field = any(f.name == "password" for f in fields)
            if not has_password_field:
                fields.append(
                    FieldDescriptor(
                        name="password",
                        type="string",
                        required=True,
                        is_optional=False,
                        constraints={"min_length": 1},
                    )
                )

        return fields

    def _model_name(self, collection: str, operation: str) -> str:
        col_part = "".join(part.capitalize() for part in collection.split("_"))
        return f"{col_part}{operation.capitalize()}Payload"
