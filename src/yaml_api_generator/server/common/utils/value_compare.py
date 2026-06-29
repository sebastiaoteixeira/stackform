from typing import Any
from uuid import UUID

try:
    from bson import ObjectId

    _IDISH = (UUID, ObjectId)
except ImportError:
    _IDISH = (UUID,)


def values_equal(left: Any, right: Any) -> bool:
    """Compare two values by value, falling back to identifier string form.

    Request payloads carry identifiers as strings while persisted records hold
    them as native types (UUID, ObjectId). Comparing the canonical string forms
    lets equal identifiers match across that representational gap.

    The string-form fallback is confined to identifier-like operands. Booleans,
    numbers and plain scalars never coerce, so ``"1" == 1`` and ``"True" == True``
    stay false and access rules cannot be bypassed through type confusion.
    """
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if left == right:
        return True
    if isinstance(left, _IDISH) or isinstance(right, _IDISH):
        return str(left) == str(right)
    return False
