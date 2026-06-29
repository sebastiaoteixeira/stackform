"""DTO configuration transformation to IR.

A DTO is an entity stripped of persistence: fields and validators only, no id,
no repository/service, no storage-only attributes.
"""

from typing import Any, cast

from yaml_api_generator.ir import IRDto
from yaml_api_generator.parsers.transformers.name_validation import validate_name
from yaml_api_generator.parsers.yaml_parser import ConfigError


class DtoTransformer:
    """Transforms top-level dto definitions to IR."""

    def transform(
        self, dtos_data: dict[str, Any]
    ) -> tuple[dict[str, IRDto], list[ConfigError]]:
        dtos: dict[str, IRDto] = {}
        errors: list[ConfigError] = []
        for name, cfg in dtos_data.items():
            if not isinstance(cfg, dict):
                continue
            fields = cast(dict[str, Any], cfg.get("fields", {}))
            errors.extend(
                error
                for field_name in fields
                if (error := validate_name(
                    field_name, f"dto.{name}.fields.{field_name}", field=True
                )) is not None
            )
            dtos[name] = IRDto(name=name, fields=fields)
        return dtos, errors
