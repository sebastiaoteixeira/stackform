"""Container-shape guards for the pre-desugar v0.2 spec.

Desugaring dereferences the top-level blocks as mappings (``.items()``,
``.get()``) before JSON-schema validation runs. A block authored as the wrong
container type (a list or scalar where a mapping is expected) would otherwise
crash desugar with a raw ``AttributeError`` instead of a clean
``SCHEMA_VALIDATION_ERROR``. These guards run on the pre-desugar spec, mirroring
``validate_spec_names``.
"""

from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError

# Top-level blocks desugar treats as mappings of named definitions.
_MAPPING_BLOCKS = ("entities", "repositories", "services", "controllers", "api")


def _shape_error(path: str, value: Any) -> ConfigError:
    return ConfigError(
        code="SCHEMA_VALIDATION_ERROR",
        message=f"'{path}' must be an object, got {type(value).__name__}",
        path=path,
        hint="Define it as a mapping of named entries",
    )


def validate_spec_shape(spec: dict[str, Any]) -> list[ConfigError]:
    """Reject top-level blocks that desugar would dereference as the wrong type."""
    errors = [
        _shape_error(block, spec[block])
        for block in _MAPPING_BLOCKS
        if block in spec and not isinstance(spec[block], dict)
    ]
    api = spec.get("api")
    if isinstance(api, dict) and "operations" in api and not isinstance(api["operations"], dict):
        errors.append(_shape_error("api.operations", api["operations"]))
    return errors
