"""Generic single-inheritance desugarer for repository and service layers.

Mirrors EntityDesugarer's validate/cycle-detect/resolve pattern but instead of
flattening fields it resolves a chain of ``base`` import paths that the code
generator uses to emit user-authored base-class inheritance.
"""

from typing import Any

from ..yaml_parser import ConfigError, ConfigErrors


class InheritanceDesugarer:
    """Resolve ``abstract``/``extends``/``base`` for a named config layer.

    Args:
        layer: Human-readable layer name used in error codes/paths
               (e.g. ``"repository"`` or ``"service"``).
    """

    def __init__(self, layer: str) -> None:
        self._layer = layer

    def resolve_base_classes(self, entries: dict[str, Any]) -> dict[str, tuple[str, ...]]:
        """Validate inheritance and return resolved base-class chains.

        Validates that every ``extends`` target exists and is abstract, detects
        cycles, then resolves the ``base`` dotted-path chain (most-derived
        ancestor first) for each concrete entry.

        Args:
            entries: Raw config dict for the layer (repositories or services).

        Returns:
            Mapping from concrete entry name to an ordered tuple of dotted
            import paths (e.g. ``("app.bases.AuditedRepository",)``).

        Raises:
            ConfigErrors: On missing/non-abstract extends target or cycle.
        """
        self._validate(entries)
        self._validate_no_cycles(entries)
        return {
            name: self._resolve_chain(name, entries)
            for name, cfg in entries.items()
            if isinstance(cfg, dict) and not cfg.get("abstract")
            and cfg.get("extends") is not None
        }

    def remove_abstract(self, entries: dict[str, Any]) -> None:
        """Remove abstract entries in-place (called after resolution)."""
        for name in [k for k, v in entries.items() if isinstance(v, dict) and v.get("abstract")]:
            del entries[name]

    def validate_not_bound(
        self,
        entries: dict[str, Any],
        bindings: dict[str, Any],
        binding_field: str,
        *,
        error_code: str,
    ) -> None:
        """Ensure abstract entries are not referenced by controllers/routes.

        Args:
            entries: The layer dict (repositories or services).
            bindings: The dict that references entries (e.g. controllers).
            binding_field: Field name in each binding that holds the reference.
            error_code: Error code to use if a violation is found.
        """
        abstract_names = {
            name for name, cfg in entries.items()
            if isinstance(cfg, dict) and cfg.get("abstract")
        }
        errors: list[ConfigError] = []
        for binding_name, binding_cfg in bindings.items():
            if not isinstance(binding_cfg, dict):
                continue
            ref = binding_cfg.get(binding_field)
            if ref in abstract_names:
                errors.append(ConfigError(
                    code=error_code,
                    message=f"'{binding_name}' references abstract {self._layer} '{ref}'",
                    path=f"{self._layer}s.{binding_name}.{binding_field}",
                ))
        if errors:
            raise ConfigErrors(errors)

    def _validate(self, entries: dict[str, Any]) -> None:
        errors: list[ConfigError] = []
        for name, cfg in entries.items():
            if not isinstance(cfg, dict):
                continue
            parent = cfg.get("extends")
            if parent is None:
                continue
            if parent not in entries:
                errors.append(ConfigError(
                    code=f"{self._layer.upper()}_EXTENDS_NOT_FOUND",
                    message=f"{self._layer.capitalize()} '{name}' extends unknown {self._layer} '{parent}'",
                    path=f"{self._layer}s.{name}.extends",
                ))
            elif not (isinstance(entries[parent], dict) and entries[parent].get("abstract")):
                errors.append(ConfigError(
                    code=f"{self._layer.upper()}_EXTENDS_NOT_ABSTRACT",
                    message=f"{self._layer.capitalize()} '{name}' extends '{parent}' which is not abstract",
                    path=f"{self._layer}s.{name}.extends",
                ))
        if errors:
            raise ConfigErrors(errors)

    def _validate_no_cycles(self, entries: dict[str, Any]) -> None:
        errors: list[ConfigError] = []
        for name in entries:
            visited: set[str] = set()
            current: str | None = name
            while current is not None:
                if current in visited:
                    errors.append(ConfigError(
                        code=f"{self._layer.upper()}_CIRCULAR_EXTENDS",
                        message=f"Circular inheritance detected involving {self._layer} '{name}'",
                        path=f"{self._layer}s.{name}.extends",
                    ))
                    break
                visited.add(current)
                cfg = entries.get(current)
                current = cfg.get("extends") if isinstance(cfg, dict) else None
        if errors:
            raise ConfigErrors(errors)

    def _resolve_chain(self, name: str, entries: dict[str, Any]) -> tuple[str, ...]:
        """Walk the extends chain and collect ``base`` paths (most-derived first)."""
        bases: list[str] = []
        current: str | None = entries[name].get("extends") if isinstance(entries.get(name), dict) else None
        while current is not None:
            cfg = entries.get(current)
            if not isinstance(cfg, dict):
                break
            base_path = cfg.get("base")
            if base_path:
                bases.append(base_path)
            current = cfg.get("extends")
        return tuple(bases)
