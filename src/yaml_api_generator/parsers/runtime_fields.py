"""Runtime field classification for YAML spec interpolation.

A path tuple is runtime-classified when its value must survive as an EnvRef
rather than being baked at parse time. Secrets are a strict subset: the env
var is never resolved even when currently exported.
"""

from typing import Callable


# Each entry is (secret, predicate(path_tuple) -> bool).
# The predicate returns True when the path matches a runtime field.
_REGISTRY: list[tuple[bool, Callable[[tuple[str, ...]], bool]]] = [
    (True,  lambda p: len(p) >= 3 and p[0] == "providers" and p[2] == "client_secret"),
    (False, lambda p: len(p) >= 3 and p[0] == "providers" and p[2] == "discovery_url"),
    (False, lambda p: len(p) >= 3 and p[0] == "providers" and p[2] == "idp_metadata_url"),
    (False, lambda p: len(p) >= 3 and p[0] == "providers" and p[2] == "sp_entity_id"),
    (True,  lambda p: len(p) >= 2 and p[0] in ("datastores", "mongo") and p[-1] == "password"),
]


def classify(path: tuple[str, ...]) -> tuple[bool, bool]:
    """Return (is_runtime, is_secret) for the given path tuple.

    Both flags are False for build-time (structural) fields.
    """
    for secret, predicate in _REGISTRY:
        if predicate(path):
            return True, secret
    return False, False
