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