"""V0.3 YAML to IR transformation orchestrator.

v0.3 is a superset of v0.2 and enables the version-specific where-binding and
service input/forwarding grammar.
"""

from ..v02 import V02Transformer
from ..v02.access_transformer import AccessTransformer
from ..v02.route_transformer import RouteTransformer


class V03Transformer(V02Transformer):
    """Orchestrates v0.3 YAML to IR transformation."""

    def __init__(self) -> None:
        super().__init__()
        self._access = AccessTransformer(allow_where=True)
        self._route = RouteTransformer(self._access, allow_service_inputs=True)
