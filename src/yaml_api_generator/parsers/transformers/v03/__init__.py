"""V0.3 YAML to IR transformation orchestrator.

v0.3 is a superset of v0.2. This transformer inherits the full v0.2 pipeline
unchanged; the v0.3-specific constructs (where binding form, service input/with,
controller bind) gain their semantics in later v0.3 issues.
"""

from ..v02 import V02Transformer
from ..v02.access_transformer import AccessTransformer
from ..v02.route_transformer import RouteTransformer


class V03Transformer(V02Transformer):
    """Orchestrates v0.3 YAML to IR transformation."""

    def __init__(self) -> None:
        super().__init__()
        self._access = AccessTransformer(allow_where=True)
        self._route = RouteTransformer(self._access)
