"""Validation for user-supplied names emitted verbatim into generated Python.

Field, entity, repository, service, controller and provider names become Python
identifiers, attributes, module names and Pydantic model fields. Names that are
syntactically valid identifiers but collide with Python keywords or the Pydantic
``BaseModel`` API compile fine yet break at import time (``SyntaxError`` for
keywords, ``PydanticUserError`` for shadowed model internals), so they must be
rejected during transformation.
"""

import keyword
import re
from typing import Any

from yaml_api_generator.parsers.yaml_parser import ConfigError

NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")

# Names that shadow the Pydantic BaseModel API. A field carrying one of these
# names raises a PydanticUserError when the generated model is imported.
PYDANTIC_RESERVED_NAMES = frozenset({
    "model_config", "model_fields", "model_computed_fields", "model_extra",
    "model_fields_set", "model_construct", "model_copy", "model_dump",
    "model_dump_json", "model_json_schema", "model_parametrized_name",
    "model_post_init", "model_rebuild", "model_validate", "model_validate_json",
    "model_validate_strings", "construct", "copy", "dict", "json", "parse_obj",
    "parse_raw", "parse_file", "from_orm", "schema", "schema_json", "validate",
    "update_forward_refs", "fields", "Config",
})


def _reserved_reason(name: str) -> str | None:
    if keyword.iskeyword(name) or keyword.issoftkeyword(name):
        return "is a Python keyword"
    if name in PYDANTIC_RESERVED_NAMES or name.startswith("model_"):
        return "shadows the Pydantic BaseModel API"
    return None


def validate_name(name: str, path: str, *, field: bool = False) -> ConfigError | None:
    """Return a ConfigError if ``name`` is unusable as a Python identifier.

    ``field`` selects the INVALID_FIELD_NAME code for field names; all other
    name-bearing keys use INVALID_NAME.
    """
    code = "INVALID_FIELD_NAME" if field else "INVALID_NAME"
    kind = "Field" if field else "Name"
    if not NAME_PATTERN.match(name):
        return ConfigError(
            code=code,
            message=f"Invalid {kind.lower()} '{name}'",
            path=path,
            hint="Names must start with a letter and contain only letters, numbers, or underscores",
        )
    reason = _reserved_reason(name)
    if reason is not None:
        return ConfigError(
            code=code,
            message=f"Invalid {kind.lower()} '{name}': it {reason}",
            path=path,
            hint="Choose a name that is not a Python keyword and does not shadow the Pydantic BaseModel API",
        )
    return None


# Top-level spec sections whose keys are emitted verbatim as Python identifiers,
# module names, attributes or classes. Provider names are excluded: they are only
# used as route-path segments and as identifiers after sanitization (py_identifier),
# so hyphenated names such as ``my-oidc`` are valid.
_NAME_BEARING_SECTIONS = ("entities", "repositories", "services", "controllers")


def validate_spec_names(spec: dict[str, Any]) -> list[ConfigError]:
    """Validate every name-bearing key in a user-authored v0.2 spec.

    Operates on the pre-desugar spec so that only author-supplied names are
    checked; field names are validated per entity in addition to the top-level
    section keys.
    """
    errors: list[ConfigError] = []
    for section in _NAME_BEARING_SECTIONS:
        data = spec.get(section)
        if not isinstance(data, dict):
            continue
        for name in data:
            error = validate_name(str(name), f"{section}.{name}")
            if error is not None:
                errors.append(error)
    for entity_name, entity in (spec.get("entities") or {}).items():
        if not isinstance(entity, dict):
            continue
        for field_name in entity.get("fields", {}):
            error = validate_name(
                str(field_name),
                f"entities.{entity_name}.fields.{field_name}",
                field=True,
            )
            if error is not None:
                errors.append(error)
    return errors
