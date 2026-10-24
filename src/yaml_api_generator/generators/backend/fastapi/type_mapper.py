"""Field configs rendered as the declarations of a pydantic payload module."""

from dataclasses import dataclass
from typing import Any

from yaml_api_generator.runtime.fields import is_open
from yaml_api_generator.runtime.payloads import CONSTRAINTS, SCALAR_TYPES, STRICT_TYPES
from yaml_api_generator.utils.strings import to_pascal_case
from yaml_api_generator.generators.backend.compile_context import ModelDescriptor


_IMPORTS: dict[str, tuple[str, ...]] = {
    "typing": ("Annotated", "Any", "Literal"),
    "pydantic": ("Field",),
    "dependencies.payloads": ("OpenPayload", "Payload", "Timestamp", "formatted", "partial"),
}


@dataclass(frozen=True)
class Attribute:
    name: str
    annotation: str
    default: str | None


@dataclass(frozen=True)
class ClassDeclaration:
    """A payload class; ``readonly`` fields are rejected and ``server_defaults`` added on dump."""

    name: str
    base: str
    attributes: tuple[Attribute, ...]
    readonly: frozenset[str] = frozenset()
    server_defaults: dict[str, Any] | None = None


@dataclass(frozen=True)
class PartialDeclaration:
    """``name`` is ``base`` with every field omittable."""

    name: str
    base: str


class PayloadModule:
    """The declarations of one generated models module and the imports they use.

    Nested object models are declared before the model that refers to them.
    """

    def __init__(self, models: list[ModelDescriptor]) -> None:
        self.declarations: list[ClassDeclaration | PartialDeclaration] = []
        self._used: set[str] = set()
        for model in models:
            self._declare(model)

    @property
    def imports(self) -> list[str]:
        return [
            f"from {module} import {', '.join(used)}"
            for module, names in _IMPORTS.items()
            if (used := [name for name in names if name in self._used])
        ]

    def _use(self, name: str) -> str:
        self._used.add(name)
        return name

    def _declare(self, model: ModelDescriptor) -> None:
        if model.operation == "update":
            self._use("partial")
            self.declarations.append(PartialDeclaration(model.name, model.base))
            return
        self._class(
            model.name,
            model.base or self._use("Payload"),
            {field.name: field.config for field in model.fields},
            owner=to_pascal_case(model.collection),
        )

    def _class(
        self, name: str, base: str, properties: dict[str, dict[str, Any]], owner: str
    ) -> None:
        if any(declaration.name == name for declaration in self.declarations):
            raise ValueError(f"Two payload models are both named '{name}'")
        readonly = {field: config for field, config in properties.items() if config.get("readonly")}
        attributes = tuple(
            self._attribute(f"{owner}{to_pascal_case(field)}", field, config)
            for field, config in properties.items()
            if field not in readonly
        )
        server_defaults = {field: config["default"] for field, config in readonly.items() if "default" in config}
        self.declarations.append(
            ClassDeclaration(name, base, attributes, frozenset(readonly), server_defaults or None)
        )

    def _attribute(self, nested_name: str, name: str, config: dict[str, Any]) -> Attribute:
        annotation = self._annotation(config, nested_name)
        if config.get("required"):
            return Attribute(name, annotation, repr(config["default"]) if "default" in config else None)
        return Attribute(name, f"{annotation} | None", repr(config.get("default")))

    def _annotation(self, config: dict[str, Any], nested_name: str) -> str:
        kind = config.get("type", "string")
        if kind == "enum":
            return f"{self._use('Literal')}[{', '.join(map(repr, config['values']))}]"
        if kind == "array":
            items = config.get("items")
            item = self._annotation(items, f"{nested_name}Item") if items else self._use("Any")
            return f"list[{item}]"
        if kind == "object":
            return self._object(config, nested_name)
        return self._scalar(config, SCALAR_TYPES[kind])

    def _object(self, config: dict[str, Any], name: str) -> str:
        if "properties" not in config and is_open(config):
            return f"dict[str, {self._use('Any')}]"
        base = self._use("OpenPayload" if is_open(config) else "Payload")
        self._class(name, base, config.get("properties", {}), owner=name)
        return name

    def _scalar(self, config: dict[str, Any], scalar: type) -> str:
        python_type = self._use(scalar.__name__)
        arguments = {
            **({"strict": True} if scalar in STRICT_TYPES else {}),
            **{CONSTRAINTS[key]: config[key] for key in CONSTRAINTS if key in config},
        }
        listed = ", ".join(f"{key}={value!r}" for key, value in arguments.items())
        field = [f"{self._use('Field')}({listed})"] if arguments else []
        formatted = [f"{self._use('formatted')}({config['format']!r})"] if "format" in config else []
        metadata = [*field, *formatted]
        if not metadata:
            return python_type
        return f"{self._use('Annotated')}[{python_type}, {', '.join(metadata)}]"
