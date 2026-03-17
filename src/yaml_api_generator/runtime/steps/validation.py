from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..context import RequestContext
from ..runtime_context import RuntimeCollectionDescriptor, RuntimeIdentityDescriptor
from . import Step


_NO_BODY_OPS = frozenset({"list", "get", "delete"})


@dataclass(frozen=True)
class _FieldSchema:
    name: str
    field_type: str
    required: bool
    min: float | None = None
    max: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    enum_values: list[str] | None = None


def _build_field_schemas(
    collection: RuntimeCollectionDescriptor,
    operation: str,
    identity_collection: RuntimeIdentityDescriptor | None = None,
) -> list[_FieldSchema]:
    schemas: list[_FieldSchema] = []
    make_optional = operation == "update"

    for field_name, raw_config in collection.fields.items():
        if not isinstance(raw_config, dict):
            continue
        if raw_config.get("type") == "id":
            continue
        if field_name == "passwordHash":
            continue

        required = not make_optional and bool(raw_config.get("required", False))
        schemas.append(_FieldSchema(
            name=field_name,
            field_type=raw_config.get("type", "string"),
            required=required,
            min=raw_config.get("min"),
            max=raw_config.get("max"),
            min_length=raw_config.get("minLength"),
            max_length=raw_config.get("maxLength"),
            enum_values=raw_config.get("values"),
        ))

    if (
        identity_collection is not None
        and operation == "create"
        and "password" in identity_collection.via
        and not any(s.name == "password" for s in schemas)
    ):
        schemas.append(_FieldSchema(
            name="password", field_type="string", required=True, min_length=1,
        ))

    return schemas


def _build_login_schemas(
    identity_collection: RuntimeIdentityDescriptor,
) -> list[_FieldSchema]:
    schemas: list[_FieldSchema] = []
    if identity_collection.identifier:
        schemas.append(_FieldSchema(
            name=identity_collection.identifier,
            field_type="string",
            required=True,
            min_length=1,
        ))
    schemas.append(_FieldSchema(
        name="password", field_type="string", required=True, min_length=1,
    ))
    return schemas


def _validate_type(name: str, value: Any, schema: _FieldSchema) -> None:
    ft = schema.field_type

    if ft in ("string", "ref"):
        if not isinstance(value, str):
            raise ValueError(f"Field '{name}' must be a string")
        if schema.min_length is not None and len(value) < schema.min_length:
            raise ValueError(
                f"Field '{name}' must have at least {schema.min_length} characters"
            )
        if schema.max_length is not None and len(value) > schema.max_length:
            raise ValueError(
                f"Field '{name}' must have at most {schema.max_length} characters"
            )

    elif ft == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Field '{name}' must be a number")
        if schema.min is not None and value < schema.min:
            raise ValueError(f"Field '{name}' must be >= {schema.min}")
        if schema.max is not None and value > schema.max:
            raise ValueError(f"Field '{name}' must be <= {schema.max}")

    elif ft == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"Field '{name}' must be a boolean")

    elif ft == "datetime":
        if not isinstance(value, str):
            raise ValueError(f"Field '{name}' must be a datetime string")
        try:
            datetime.fromisoformat(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Field '{name}' is not a valid ISO datetime") from exc

    elif ft == "enum":
        if schema.enum_values is not None and value not in schema.enum_values:
            raise ValueError(
                f"Field '{name}' must be one of: {', '.join(schema.enum_values)}"
            )

    elif ft == "array":
        if not isinstance(value, list):
            raise ValueError(f"Field '{name}' must be an array")

    elif ft == "object":
        if not isinstance(value, dict):
            raise ValueError(f"Field '{name}' must be an object")


def ValidateBodyStep(
    collection: RuntimeCollectionDescriptor,
    operation: str,
    identity_collection: RuntimeIdentityDescriptor | None = None,
) -> Step:
    if operation == "login":
        if identity_collection is None:
            raise ValueError("login operation requires an identity collection")
        field_schemas = _build_login_schemas(identity_collection)
    else:
        field_schemas = _build_field_schemas(collection, operation, identity_collection)

    known_fields = {s.name for s in field_schemas}
    schema_by_name = {s.name: s for s in field_schemas}

    def step(ctx: RequestContext) -> RequestContext:
        if operation in _NO_BODY_OPS:
            return ctx

        body = ctx.body
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")

        unknown = set(body.keys()) - known_fields
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

        if operation != "update":
            missing = [s.name for s in field_schemas if s.required and s.name not in body]
            if missing:
                raise ValueError(f"Missing required fields: {', '.join(missing)}")

        for key, value in body.items():
            schema = schema_by_name.get(key)
            if schema is not None:
                _validate_type(key, value, schema)

        return ctx

    return step
