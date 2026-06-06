"""String manipulation utilities."""

import re


def to_pascal_case(name: str) -> str:
    """Convert any naming convention to PascalCase.

    Handles snake_case, camelCase, kebab-case, PascalCase, and mixed formats.

    Examples:
        >>> to_pascal_case("user_profile")
        'UserProfile'
        >>> to_pascal_case("userProfile")
        'UserProfile'
        >>> to_pascal_case("user-profile")
        'UserProfile'
        >>> to_pascal_case("UserProfile")
        'UserProfile'
        >>> to_pascal_case("user")
        'User'
    """
    parts = re.split(r'[_-]+|(?<=[a-z0-9])(?=[A-Z])', name)
    return "".join(part.capitalize() for part in parts if part)


def to_py_identifier(name: str) -> str:
    """Sanitize an arbitrary name into a valid Python identifier.

    Non-identifier characters become underscores and a leading digit is
    prefixed with an underscore. Intended for generated symbol names only;
    the original name must still be used wherever it is semantically
    meaningful (route paths, provider lookups).
    """
    sanitized = re.sub(r'\W', '_', name)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized