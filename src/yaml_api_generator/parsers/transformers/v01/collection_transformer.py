"""Collection transformation for v0.1 specifications.

Validates collection fields and extracts ID field configurations.
"""

from typing import Any, cast

from yaml_api_generator.ir import IRCollection
from yaml_api_generator.parsers.transformers.lifecycle_binding import bind_lifecycle
from yaml_api_generator.parsers.yaml_parser import ConfigError
from yaml_api_generator.runtime.lifecycle import Lifecycle

SOFT_DELETE_FIELD = "deletedAt"

class CollectionTransformer:
    """Transforms v0.1 collection definitions to IR."""

    def transform(
        self,
        collections_data: dict[str, Any],
    ) -> tuple[dict[str, IRCollection], dict[str, dict[str, Any]], list[ConfigError]]:
        """Transform collection definitions to IR.

        Args:
            collections_data: Raw collection configurations from YAML

        Returns:
            Tuple of (collections dict, access policies dict, validation errors)
        """
        collections: dict[str, IRCollection] = {}
        collection_access_policies: dict[str, dict[str, Any]] = {}
        id_field_errors: list[ConfigError] = []

        for name, collection_data in collections_data.items():
            collection_type = str(collection_data.get("type", "base"))
            fields = cast(dict[str, Any], collection_data["fields"])

            id_field, errors = self._extract_id_field(name, fields)
            id_field_errors.extend(errors)

            id_format: str | None = None
            if id_field is not None:
                id_format, format_errors = self._resolve_id_format(
                    name, id_field, fields
                )
                id_field_errors.extend(format_errors)

            raw_access = collection_data.get("access")
            collection_access_policies[name] = (
                raw_access if isinstance(raw_access, dict) else {}
            )

            if id_field is None or id_format is None:
                continue

            lifecycle = Lifecycle(
                removal=SOFT_DELETE_FIELD if collection_data.get("softDelete") else None
            )
            bound_fields, lifecycle_errors = bind_lifecycle(
                lifecycle, fields, f"collections.{name}"
            )
            id_field_errors.extend(lifecycle_errors)

            collections[name] = IRCollection(
                name=name,
                entity_name=name,
                type=collection_type,
                idField=id_field,
                idFormat=id_format,
                fields=bound_fields,
                lifecycle=lifecycle,
            )

        return collections, collection_access_policies, id_field_errors

    def _extract_id_field(
        self, collection_name: str, fields: dict[str, Any]
    ) -> tuple[str | None, list[ConfigError]]:
        id_fields = [
            field_name
            for field_name, field_config in fields.items()
            if isinstance(field_config, dict) and field_config.get("type") == "id"
        ]
        if len(id_fields) == 1:
            return id_fields[0], []
        if not id_fields:
            return None, [
                ConfigError(
                    code="ID_FIELD_MISSING",
                    message="Collection must define exactly one field with type 'id'",
                    path=f"collections.{collection_name}.fields",
                )
            ]
        return None, [
            ConfigError(
                code="ID_FIELD_MULTIPLE",
                message="Collection must define exactly one field with type 'id'",
                path=f"collections.{collection_name}.fields",
                hint=f"Found multiple id fields: {', '.join(id_fields)}",
            )
        ]

    def _resolve_id_format(
        self, collection_name: str, id_field: str, fields: dict[str, Any]
    ) -> tuple[str | None, list[ConfigError]]:
        field_config = fields.get(id_field)
        if not isinstance(field_config, dict):
            return None, [
                ConfigError(
                    code="ID_FIELD_INVALID",
                    message="Collection id field configuration is invalid",
                    path=f"collections.{collection_name}.fields.{id_field}",
                )
            ]
        return str(field_config.get("format", "uuidv7")), []
