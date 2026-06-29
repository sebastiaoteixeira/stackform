from typing import Any


def values_equal(left: Any, right: Any) -> bool:
    """Compare two values by identity, falling back to string form.

    Request payloads carry identifiers as strings while persisted records hold
    them as native types (UUID, ObjectId, datetime). Comparing the canonical
    string forms lets equal values match across that representational gap.
    """
    if left == right:
        return True
    if left is None or right is None:
        return False
    return str(left) == str(right)
