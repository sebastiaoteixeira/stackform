from ...compile_context import FieldDescriptor


_TYPE_MAP: dict[str, str] = {
    "string": "serializers.CharField",
    "ref": "serializers.CharField",
    "number": "serializers.FloatField",
    "boolean": "serializers.BooleanField",
    "datetime": "serializers.DateTimeField",
    "object": "serializers.DictField",
}


def drf_field(field: FieldDescriptor) -> str:
    """Return the DRF serializer field instantiation string."""
    kwargs: list[str] = []

    if field.is_optional:
        kwargs.append("required=False")
        kwargs.append("allow_null=True")
    elif not field.required:
        kwargs.append("required=False")

    if field.default is not None:
        kwargs.append(f"default={field.default!r}")

    if field.type == "enum" and field.enum_values:
        choices = [f'"{v}"' for v in field.enum_values]
        kwargs.append(f"choices=[{', '.join(choices)}]")
        return f"serializers.ChoiceField({', '.join(kwargs)})"

    if field.type == "array":
        inner = _TYPE_MAP.get(field.array_item_type or "string", "serializers.CharField")
        kwargs.append(f"child={inner}()")
        return f"serializers.ListField({', '.join(kwargs)})"

    base = _TYPE_MAP.get(field.type, "serializers.CharField")

    if field.constraints.get("min") is not None:
        kwargs.append(f"min_value={field.constraints['min']}")
    if field.constraints.get("max") is not None:
        kwargs.append(f"max_value={field.constraints['max']}")
    if field.constraints.get("min_length") is not None:
        kwargs.append(f"min_length={field.constraints['min_length']}")
    if field.constraints.get("max_length") is not None:
        kwargs.append(f"max_length={field.constraints['max_length']}")

    return f"{base}({', '.join(kwargs)})"
