from yaml_api_generator.generators.backend.compile_context import FieldDescriptor
from yaml_api_generator.generators.backend.constraint_utils import extract_numeric_constraints, extract_string_constraints


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
        choices = [repr(v) for v in field.enum_values]
        kwargs.append(f"choices=[{', '.join(choices)}]")
        return f"serializers.ChoiceField({', '.join(kwargs)})"

    if field.type == "array":
        inner = _TYPE_MAP.get(field.array_item_type or "string", "serializers.CharField")
        kwargs.append(f"child={inner}()")
        return f"serializers.ListField({', '.join(kwargs)})"

    base = _TYPE_MAP.get(field.type, "serializers.CharField")

    numeric_constraints = extract_numeric_constraints(field)
    if "min" in numeric_constraints:
        kwargs.append(f"min_value={numeric_constraints['min']}")
    if "max" in numeric_constraints:
        kwargs.append(f"max_value={numeric_constraints['max']}")

    string_constraints = extract_string_constraints(field)
    if "min_length" in string_constraints:
        kwargs.append(f"min_length={string_constraints['min_length']}")
    if "max_length" in string_constraints:
        kwargs.append(f"max_length={string_constraints['max_length']}")

    return f"{base}({', '.join(kwargs)})"
