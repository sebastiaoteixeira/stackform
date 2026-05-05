"""Collection configuration transformation to IR.

Validates entity definitions and builds collection IR objects.
"""

import re
from typing import Any, cast

from yaml_api_generator.ir import IRCollection
from yaml_api_generator.parsers.yaml_parser import ConfigError

FIELD_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


class CollectionTransformer:
    """Transforms entity definitions to collection IR."""

    def transform(
        self,
        entities_data: dict[str, Any],
        repos_data: dict[str, Any],
        defaults: dict[str, Any],
    ) -> tuple[dict[str, IRCollection], list[ConfigError]]:
        """Transform entity definitions to IR collections.

        Args:
            entities_data: Raw entity configurations from YAML
            repos_data: Raw repository configurations from YAML
            defaults: Default operation configuration

        Returns:
            Tuple of (collections dict, validation errors)
        """
        collections: dict[str, IRCollection] = {}
        errors: list[ConfigError] = []

        for repo_name, repo_cfg in repos_data.items():
            if not isinstance(repo_cfg, dict):
                continue
            entity_name = repo_cfg.get("entity")
            if not entity_name:
                continue
            entity_data = entities_data.get(entity_name)
            if not isinstance(entity_data, dict):
                errors.append(
                    ConfigError(
                        code="ENTITY_NOT_FOUND",
                        message=f"Repository '{repo_name}' references unknown entity '{entity_name}'",
                        path=f"repositories.{repo_name}.entity",
                    )
                )
                continue

            entity_type = str(entity_data.get("type", "base"))
            fields = cast(dict[str, Any], entity_data.get("fields", {}))

            field_errors = self._validate_field_names(entity_name, fields)
            errors.extend(field_errors)
            if field_errors:
                continue

            pk_field = entity_data.get("pk")
            if pk_field is not None:
                if pk_field not in fields:
                    errors.append(
                        ConfigError(
                            code="PK_FIELD_NOT_FOUND",
                            message=f"pk field '{pk_field}' not found in entity '{entity_name}'",
                            path=f"entities.{entity_name}.pk",
                        )
                    )
                    continue
                id_field, id_format = pk_field, "natural"
            else:
                id_field_result, id_errors = self._extract_entity_id_field(entity_name, fields)
                errors.extend(id_errors)
                id_format_result: str | None = None
                if id_field_result is not None:
                    id_format_result, fmt_errors = self._resolve_id_format(
                        entity_name, id_field_result, fields
                    )
                    errors.extend(fmt_errors)
                if id_field_result is None or id_format_result is None:
                    continue
                id_field, id_format = id_field_result, id_format_result

            collections[repo_name] = IRCollection(
                name=repo_name,
                entity_name=entity_name,
                type=entity_type,
                idField=id_field,
                idFormat=id_format,
                fields=fields,
            )

        return collections, errors

    def _extract_entity_id_field(
        self, entity_name: str, fields: dict[str, Any]
    ) -> tuple[str | None, list[ConfigError]]:
        id_fields = [
            name for name, cfg in fields.items()
            if isinstance(cfg, dict) and cfg.get("type") == "id"
        ]
        if len(id_fields) == 1:
            return id_fields[0], []
        if not id_fields:
            return None, [
                ConfigError(
                    code="ID_FIELD_MISSING",
                    message="Entity must define exactly one field with type 'id'",
                    path=f"entities.{entity_name}.fields",
                )
            ]
        return None, [
            ConfigError(
                code="ID_FIELD_MULTIPLE",
                message="Entity must define exactly one field with type 'id'",
                path=f"entities.{entity_name}.fields",
                hint=f"Found multiple id fields: {', '.join(id_fields)}",
            )
        ]

    def _resolve_id_format(
        self, entity_name: str, id_field: str, fields: dict[str, Any]
    ) -> tuple[str | None, list[ConfigError]]:
        cfg = fields.get(id_field)
        if not isinstance(cfg, dict):
            return None, [
                ConfigError(
                    code="ID_FIELD_INVALID",
                    message="Entity id field configuration is invalid",
                    path=f"entities.{entity_name}.fields.{id_field}",
                )
            ]
        raw = cfg.get("format")
        if raw is None:
            return "uuidv7", []
        if raw in {"uuidv7", "uuidv4"}:
            return str(raw), []
        return None, [
            ConfigError(
                code="ID_FORMAT_INVALID",
                message="id field format must be uuidv7 or uuidv4",
                path=f"entities.{entity_name}.fields.{id_field}.format",
            )
        ]

    def _validate_field_names(
        self, entity_name: str, fields: dict[str, Any]
    ) -> list[ConfigError]:
        errors: list[ConfigError] = []
        for field_name in fields:
            if not FIELD_NAME_PATTERN.match(field_name):
                errors.append(
                    ConfigError(
                        code="INVALID_FIELD_NAME",
                        message=f"Invalid field name '{field_name}'",
                        path=f"entities.{entity_name}.fields.{field_name}",
                        hint="Field names must start with a letter and contain only letters, numbers, or underscores",
                    )
                )
        return errors
