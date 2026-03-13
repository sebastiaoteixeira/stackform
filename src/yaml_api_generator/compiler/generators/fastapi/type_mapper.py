from ...compile_context import FieldDescriptor


_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "ref": "str",
    "number": "float",
    "boolean": "bool",
    "datetime": "datetime",
    "object": "dict[str, Any]",
}


def python_type(field: FieldDescriptor) -> str:
    if field.type == "enum" and field.enum_values:
        quoted = ", ".join(f'"{v}"' for v in field.enum_values)
        return f"Literal[{quoted}]"

    if field.type == "array":
        inner = _TYPE_MAP.get(field.array_item_type or "string", "Any")
        return f"list[{inner}]"

    return _TYPE_MAP.get(field.type, "Any")


def python_annotation(field: FieldDescriptor) -> str:
    base = python_type(field)
    if field.is_optional:
        return f"{base} | None"
    return base


def needs_datetime_import(fields: list[FieldDescriptor]) -> bool:
    return any(f.type == "datetime" for f in fields)


def needs_literal_import(fields: list[FieldDescriptor]) -> bool:
    return any(f.type == "enum" and f.enum_values for f in fields)


def needs_any_import(fields: list[FieldDescriptor]) -> bool:
    return any(
        f.type in ("object", "array") and (f.array_item_type or "string") not in _TYPE_MAP
        for f in fields
    ) or any(f.type == "object" for f in fields)
