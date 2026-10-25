"""Validation of values against spec field configs.

Shared verbatim by the development server and every generated backend, so a
field config means the same thing wherever a request lands. ``conform`` checks
one value, ``conform_object`` a key/value map and ``conform_inputs`` a service's
inputs; each returns the value with the declared defaults filled in. A
``Model`` names the properties of one request payload.
"""

import json
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID


NOT_AN_OBJECT = "Request body must be a JSON object"


class FieldError(ValueError):
    def __init__(self, path: str, problem: str) -> None:
        super().__init__(f"Field '{path}' {problem}")


def _is_uuid(version: int) -> Callable[[str], bool]:
    def check(value: str) -> bool:
        try:
            return UUID(value).version == version
        except ValueError:
            return False

    return check


def _is_uri(value: str) -> bool:
    parts = urlparse(value)
    return bool(parts.scheme and (parts.netloc or parts.path))


FORMATS: dict[str, Callable[[str], object]] = {
    "email": re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+").fullmatch,
    "e164": re.compile(r"\+[1-9]\d{1,14}").fullmatch,
    "uri": _is_uri,
    "uuidv4": _is_uuid(4),
    "uuidv7": _is_uuid(7),
}


def check_format(format_name: str, value: str, path: str = "value") -> str:
    if not FORMATS[format_name](value):
        raise FieldError(path, f"must be a valid {format_name}")
    return value


def is_open(config: dict[str, Any]) -> bool:
    """An object accepts undeclared keys unless it declares its properties."""
    return config.get("additionalProperties", "properties" not in config)


def _string(config: dict[str, Any], value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise FieldError(path, "must be a string")
    minimum, maximum = config.get("minLength"), config.get("maxLength")
    if minimum is not None and len(value) < minimum:
        raise FieldError(path, f"must have at least {minimum} characters")
    if maximum is not None and len(value) > maximum:
        raise FieldError(path, f"must have at most {maximum} characters")
    if "format" in config:
        check_format(config["format"], value, path)
    return value


def _number(config: dict[str, Any], value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FieldError(path, "must be a number")
    minimum, maximum = config.get("min"), config.get("max")
    if minimum is not None and value < minimum:
        raise FieldError(path, f"must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise FieldError(path, f"must be <= {maximum}")
    return value


def _boolean(config: dict[str, Any], value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise FieldError(path, "must be a boolean")
    return value


def iso_utc(moment: datetime) -> str:
    """``moment`` as an ISO 8601 UTC timestamp; a naive one is taken as UTC."""
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


def canonical_datetime(value: str) -> str:
    """``value`` in the form ``iso_utc`` gives."""
    return iso_utc(datetime.fromisoformat(value))


def _datetime(config: dict[str, Any], value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise FieldError(path, "must be a datetime string")
    try:
        return canonical_datetime(value)
    except ValueError as exc:
        raise FieldError(path, "is not a valid ISO datetime") from exc


def _enum(config: dict[str, Any], value: Any, path: str) -> Any:
    choices = config.get("values", [])
    if value not in choices:
        raise FieldError(path, f"must be one of: {', '.join(map(str, choices))}")
    return value


def _array(config: dict[str, Any], value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise FieldError(path, "must be an array")
    if "items" not in config:
        return value
    return [
        conform(config["items"], item, f"{path}[{index}]")
        for index, item in enumerate(value)
    ]


def _object(config: dict[str, Any], value: Any, path: str) -> dict[str, Any]:
    return conform_object(
        config.get("properties", {}), value, open=is_open(config), path=path
    )


_TYPES: dict[str, Callable[[dict[str, Any], Any, str], Any]] = {
    "string": _string,
    "id": _string,
    "ref": _string,
    "number": _number,
    "boolean": _boolean,
    "datetime": _datetime,
    "enum": _enum,
    "array": _array,
    "object": _object,
}


def conform(config: dict[str, Any], value: Any, path: str) -> Any:
    return _TYPES[config.get("type", "string")](config, value, path)


def _conform_property(config: dict[str, Any], value: Any, path: str) -> Any:
    """A property may be null unless it is required."""
    if value is None and not config.get("required"):
        return None
    if value is None:
        raise FieldError(path, "is required and cannot be null")
    return conform(config, value, path)


def conform_object(
    properties: dict[str, dict[str, Any]],
    value: dict[str, Any],
    *,
    open: bool = False,
    partial: bool = False,
    path: str = "",
) -> dict[str, Any]:
    """Check a map against its declared properties.

    A readonly property is never accepted; its default is filled in like any
    other. ``partial`` accepts any subset of the properties and fills in no
    defaults.
    """
    if not isinstance(value, dict):
        raise FieldError(path, "must be an object") if path else ValueError(NOT_AN_OBJECT)
    qualified = (lambda name: f"{path}.{name}") if path else str
    unknown = [] if open else sorted(value.keys() - properties.keys())
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(map(qualified, unknown))}")
    readonly = sorted(name for name in value.keys() & properties.keys() if properties[name].get("readonly"))
    if readonly:
        raise ValueError(f"Readonly fields: {', '.join(map(qualified, readonly))}")
    expected = {} if partial else properties
    missing = [
        name
        for name, config in expected.items()
        if config.get("required") and not config.get("readonly") and "default" not in config
        and name not in value
    ]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(map(qualified, missing))}")
    defaults = {
        name: deepcopy(config["default"])
        for name, config in expected.items()
        if "default" in config and name not in value
    }
    return {
        **value,
        **defaults,
        **{
            name: _conform_property(properties[name], item, qualified(name))
            for name, item in value.items()
            if name in properties
        },
    }


@dataclass(frozen=True)
class Model:
    """A request payload: its properties, whether it keeps undeclared keys and whether it accepts any subset."""

    properties: dict[str, dict[str, Any]]
    open: bool = False
    partial: bool = False

    def extend(self, properties: dict[str, dict[str, Any]]) -> "Model":
        return replace(self, properties={**self.properties, **properties})

    def conform(self, value: Any) -> dict[str, Any]:
        return conform_object(self.properties, value, open=self.open, partial=self.partial)


def partial(model: Model) -> Model:
    """``model`` accepting any subset of its properties, with no defaults filled in."""
    return replace(model, partial=True)


_JSON_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")

_PATH_SCALARS: dict[str, Callable[[str], Any]] = {
    "number": lambda text: json.loads(text) if _JSON_NUMBER.fullmatch(text) else text,
    "boolean": lambda text: {"true": True, "false": False}.get(text, text),
}


def _read_path(inputs: dict[str, dict[str, Any]], path_values: dict[str, str]) -> dict[str, Any]:
    """A path segment is text; a number or boolean input reads the scalar its segment spells."""
    return {
        name: _PATH_SCALARS.get(inputs.get(name, {}).get("type"), str)(text)
        for name, text in path_values.items()
    }


def conform_inputs(
    inputs: dict[str, dict[str, Any]],
    body: Any,
    path_values: dict[str, str],
    bound_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check service inputs, each required unless it says otherwise.

    Path parameters override body fields and access bindings override both, so
    a body cannot spoof a route identity.
    """
    required_by_default = {
        name: {"required": True, **config} for name, config in inputs.items()
    }
    values = {
        **(body if isinstance(body, dict) else {}),
        **_read_path(inputs, path_values),
        **(bound_inputs or {}),
    }
    return conform_object(required_by_default, values, open=True)
