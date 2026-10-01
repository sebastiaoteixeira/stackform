"""Python source for IR dataclasses that the generated app rebuilds as their runtime twins."""

from dataclasses import fields, is_dataclass
from typing import Any

_IR_PREFIX = "IR"


def py_constructor(value: Any) -> str:
    """`IRFileField(...)` becomes the source of `FileField(...)`, recursively."""
    if not is_dataclass(value):
        return repr(value)
    arguments = ", ".join(
        f"{spec.name}={py_constructor(getattr(value, spec.name))}" for spec in fields(value)
    )
    return f"{type(value).__name__.removeprefix(_IR_PREFIX)}({arguments})"
