"""Shared constants for YAML API Generator."""
from enum import Enum
from typing import Final


CRUD_OPERATIONS: Final[tuple[str, ...]] = (
    "list", "get", "create", "update", "replace", "delete"
)

AUTH_OPERATIONS: Final[tuple[str, ...]] = ("register", "login")


CANONICAL_ID_FIELD: Final[str] = "id"
AUTH_FIELD: Final[str] = "_auth"
PASSWORD_FIELD: Final[str] = "password"


class OverwritePolicy(str, Enum):
    """Frontend file overwrite policies."""
    NEVER = "never"
    ALWAYS = "always"


class FileZone(str, Enum):
    """Frontend file zones."""
    GENERATED = "generated"
    EDITABLE = "editable"
