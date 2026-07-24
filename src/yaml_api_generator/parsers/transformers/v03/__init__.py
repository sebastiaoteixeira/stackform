"""V0.3 YAML to IR transformation orchestrator.

v0.3 is a superset of v0.2. This transformer inherits the full v0.2 pipeline
unchanged; the v0.3-specific constructs (where binding form, service input/with,
controller bind) gain their semantics in later v0.3 issues.
"""

from ..v02 import V02Transformer


class V03Transformer(V02Transformer):
    """Orchestrates v0.3 YAML to IR transformation."""
