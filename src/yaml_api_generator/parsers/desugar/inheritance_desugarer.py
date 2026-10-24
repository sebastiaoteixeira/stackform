"""Generic single-inheritance desugarer for repository and service layers."""

from typing import Any

from ..yaml_parser import ConfigError, ConfigErrors

_UNINHERITED = frozenset({"abstract", "extends"})


class InheritanceDesugarer:
    """Resolve ``abstract``/``extends`` for a named config layer.

    Args:
        layer: Human-readable layer name used in error codes/paths
               (e.g. ``"repository"`` or ``"service"``).
    """

    def __init__(self, layer: str) -> None:
        self._layer = layer

    def desugar(self, entries: dict[str, Any], bindings: dict[str, dict[str, Any]]) -> None:
        """Validate inheritance and fold every ancestor into the entries extending it.

        Every ``extends`` target must exist and be abstract, chains must not
        cycle and no binding may reference an abstract entry. Each extending
        entry receives its ancestors' configuration: its own keys win and
        ``operations`` merge per operation. ``_inherits`` names the nearest
        ancestor declaring ``operations``, rendered as the generated class the
        entry subclasses. Abstract entries without operations are dropped.

        Args:
            entries: The layer's config dict (repositories or services).
            bindings: Each config path whose ``<layer>`` key references an entry,
                mapped to the config at that path.

        Raises:
            ConfigErrors: On a missing or non-abstract target, a cycle or a bound abstract entry.
        """
        self._validate(entries)
        self._validate_no_cycles(entries)
        self._validate_not_bound(entries, bindings)
        entries.update({
            name: {**self._merged(name, entries), "_inherits": self._resolve_chain(name, entries)}
            for name, cfg in entries.items()
            if isinstance(cfg, dict) and cfg.get("extends")
        })
        for name in [
            name for name, cfg in entries.items()
            if isinstance(cfg, dict) and cfg.get("abstract") and not cfg.get("operations")
        ]:
            del entries[name]

    def _validate_not_bound(self, entries: dict[str, Any], bindings: dict[str, dict[str, Any]]) -> None:
        abstract_names = {
            name for name, cfg in entries.items()
            if isinstance(cfg, dict) and cfg.get("abstract")
        }
        errors = [
            ConfigError(
                code=f"DESUGAR_ABSTRACT_{self._layer.upper()}_BOUND",
                message=f"'{binding_name}' references abstract {self._layer} '{binding_cfg[self._layer]}'",
                path=f"{binding_name}.{self._layer}",
            )
            for binding_name, binding_cfg in bindings.items()
            if binding_cfg.get(self._layer) in abstract_names
        ]
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

    def _merged(self, name: str, entries: dict[str, Any]) -> dict[str, Any]:
        own = entries[name]
        if not own.get("extends"):
            return own
        parent = {
            key: value for key, value in self._merged(own["extends"], entries).items()
            if key not in _UNINHERITED
        }
        operations = {**parent.get("operations", {}), **own.get("operations", {})}
        return {**parent, **own, **({"operations": operations} if operations else {})}

    def _resolve_chain(self, name: str, entries: dict[str, Any]) -> str | None:
        """Find the nearest ancestor declaring ``operations`` up the chain."""
        current = entries[name].get("extends") if isinstance(entries.get(name), dict) else None
        while current is not None:
            cfg = entries.get(current)
            if not isinstance(cfg, dict):
                break
            if cfg.get("operations"):
                return current
            current = cfg.get("extends")
        return None
