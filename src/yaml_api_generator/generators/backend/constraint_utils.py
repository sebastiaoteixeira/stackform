from typing import Any

from .compile_context import FieldDescriptor


def extract_numeric_constraints(field: FieldDescriptor) -> dict[str, Any]:
    """
    Extract numeric constraints (min, max) from field.

    Returns dict with 'min' and/or 'max' keys if present.
    """
    constraints = {}
    if field.constraints.get("min") is not None:
        constraints["min"] = field.constraints["min"]
    if field.constraints.get("max") is not None:
        constraints["max"] = field.constraints["max"]
    return constraints


def extract_string_constraints(field: FieldDescriptor) -> dict[str, Any]:
    """
    Extract string constraints (min_length, max_length, pattern, format) from field.

    Returns dict with constraint keys if present.
    """
    constraints = {}
    if field.constraints.get("min_length") is not None:
        constraints["min_length"] = field.constraints["min_length"]
    if field.constraints.get("max_length") is not None:
        constraints["max_length"] = field.constraints["max_length"]
    if field.constraints.get("pattern") is not None:
        constraints["pattern"] = field.constraints["pattern"]
    if field.constraints.get("format") is not None:
        constraints["format"] = field.constraints["format"]
    return constraints


def extract_all_constraints(field: FieldDescriptor) -> dict[str, Any]:
    """
    Extract all constraints from field.

    Combines numeric and string constraints.
    """
    return {**extract_numeric_constraints(field), **extract_string_constraints(field)}


def build_constraint_kwargs(field: FieldDescriptor, mapping: dict[str, str] | None = None) -> list[str]:
    """
    Build list of constraint keyword arguments for code generation.

    Args:
        field: Field descriptor with constraints
        mapping: Optional mapping from constraint keys to parameter names
                 e.g., {"min": "min_value", "max": "max_value"}

    Returns:
        List of strings like ["min_value=5", "max_length=100"]

    Example:
        >>> field = FieldDescriptor(constraints={"min": 5, "max": 100})
        >>> build_constraint_kwargs(field, {"min": "ge", "max": "le"})
        ['ge=5', 'le=100']
    """
    if mapping is None:
        mapping = {}

    kwargs = []
    constraints = extract_all_constraints(field)

    for key, value in constraints.items():
        param_name = mapping.get(key, key)
        kwargs.append(f"{param_name}={value}")

    return kwargs
