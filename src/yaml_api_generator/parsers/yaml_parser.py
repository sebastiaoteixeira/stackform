"""
YAML parser: Load and validate YAML API specifications.

This module handles:
- YAML file loading with environment variable interpolation
- JSON schema validation
- Configuration error collection and reporting
- IR (Intermediate Representation) generation

Key functions:
- load_and_generate_ir(): Main entry point for parsing
- ConfigError/ConfigErrors: Structured error reporting

Environment variable interpolation:
- Syntax: ${VAR_NAME} or ${VAR_NAME:-default}
- Nested and default-with-reference forms resolve via a fixed-point loop
- Literal braces in a default are escaped as \\{ and \\}
- Env vars expanded before schema validation
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from ..ir import IRDocument
from ..ir.api import EnvRef
from .runtime_fields import classify

INTERPOLATION_PATTERN = re.compile(r"\$\{([^{}]*?)\}")
INTERPOLATION_TOKEN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?::-(.*))?$", re.DOTALL)
INTERPOLATION_MAX_DEPTH = 10
_BRACE_ESCAPES = ((r"\{", "\x00"), (r"\}", "\x01"))

MANIFEST_FILENAME = "api.yaml"
_MISSING = object()


@dataclass(frozen=True)
class ConfigError(Exception):
    code: str
    message: str
    path: str
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "path": self.path,
        }
        if self.hint:
            payload["hint"] = self.hint
        return payload


class ConfigErrors(Exception):
    def __init__(self, errors: list[ConfigError]):
        super().__init__("configuration has errors")
        self.errors = errors


@dataclass(frozen=True)
class ParseResult:
    ir: IRDocument
    ui_block: dict | None = None


def _join_path(parts: tuple[str, ...]) -> str:
    return ".".join(parts) if parts else "$"


def _interpolate_string(
    value: str, path: tuple[str, ...], errors: list[ConfigError]
) -> str:
    def resolve(match: re.Match[str]) -> str:
        token = INTERPOLATION_TOKEN.match(match.group(1))
        if token is None:
            return match.group(0)
        env_value = os.environ.get(token.group(1))
        if env_value is not None:
            return env_value
        return match.group(0) if token.group(2) is None else token.group(2)

    for literal, sentinel in _BRACE_ESCAPES:
        value = value.replace(literal, sentinel)

    for _ in range(INTERPOLATION_MAX_DEPTH):
        substituted = INTERPOLATION_PATTERN.sub(resolve, value)
        if substituted == value:
            break
        value = substituted

    for match in INTERPOLATION_PATTERN.finditer(value):
        token = INTERPOLATION_TOKEN.match(match.group(1))
        if token is None:
            errors.append(
                ConfigError(
                    code="INTERPOLATION_MALFORMED_TOKEN",
                    message=f"Malformed interpolation token '{match.group(0)}'",
                    path=_join_path(path),
                    hint="Use ${VAR_NAME} or ${VAR_NAME:-default}",
                )
            )
        else:
            var_name = token.group(1)
            errors.append(
                ConfigError(
                    code="INTERPOLATION_MISSING_VAR",
                    message=f"Environment variable '{var_name}' is required",
                    path=_join_path(path),
                    hint=f"Set {var_name} or use ${{{var_name}:-default}}",
                )
            )

    for literal, sentinel in _BRACE_ESCAPES:
        value = value.replace(sentinel, literal[1])
    return value


def _interpolate_deferred(value: str, secret: bool) -> str | EnvRef:
    """Resolve a runtime-classified field.

    - secret=True: always return EnvRef regardless of env state.
    - secret=False: return resolved string if env var is set/has default,
      otherwise return EnvRef so the generated settings handles it.
    """
    for literal, sentinel in _BRACE_ESCAPES:
        value = value.replace(literal, sentinel)

    # Resolve nested references iteratively (same fixed-point loop)
    def resolve_non_secret(match: re.Match[str]) -> str:
        token = INTERPOLATION_TOKEN.match(match.group(1))
        if token is None:
            return match.group(0)
        env_value = os.environ.get(token.group(1))
        if env_value is not None:
            return env_value
        return match.group(0) if token.group(2) is None else token.group(2)

    if not secret:
        resolved = value
        for _ in range(INTERPOLATION_MAX_DEPTH):
            substituted = INTERPOLATION_PATTERN.sub(resolve_non_secret, resolved)
            if substituted == resolved:
                break
            resolved = substituted
        # If fully resolved (no remaining tokens), return the string directly
        if not INTERPOLATION_PATTERN.search(resolved):
            for literal, sentinel in _BRACE_ESCAPES:
                resolved = resolved.replace(sentinel, literal[1])
            return resolved

    # Capture the first ${VAR:-default} token as an EnvRef
    match = INTERPOLATION_PATTERN.search(value)
    if match:
        token = INTERPOLATION_TOKEN.match(match.group(1))
        if token:
            for literal, sentinel in _BRACE_ESCAPES:
                value = value.replace(sentinel, literal[1])
            return EnvRef(name=token.group(1), default=token.group(2), secret=secret)

    for literal, sentinel in _BRACE_ESCAPES:
        value = value.replace(sentinel, literal[1])
    return value


def _resolve_interpolation(
    node: Any, path: tuple[str, ...], errors: list[ConfigError]
) -> Any:
    if isinstance(node, dict):
        return {
            str(key): _resolve_interpolation(value, (*path, str(key)), errors)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [
            _resolve_interpolation(item, (*path, str(index)), errors)
            for index, item in enumerate(node)
        ]
    if isinstance(node, str):
        is_runtime, is_secret = classify(path)
        if is_runtime:
            return _interpolate_deferred(node, is_secret)
        return _interpolate_string(node, path, errors)
    return node


def _load_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        pointer = "$"
        if mark is not None:
            pointer = f"line:{mark.line + 1},col:{mark.column + 1}"
        raise ConfigErrors(
            [
                ConfigError(
                    code="YAML_PARSE_ERROR",
                    message=str(error),
                    path=pointer,
                )
            ]
        ) from error


def _ensure_dict(content: Any, source: Path) -> dict[str, Any]:
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise ConfigErrors(
            [
                ConfigError(
                    code="YAML_ROOT_INVALID",
                    message="Top-level YAML document must be an object",
                    path="$",
                    hint=f"In {source}",
                )
            ]
        )
    return content


def _deep_merge(
    base: dict[str, Any],
    incoming: dict[str, Any],
    source: Path,
    provenance: dict[tuple[str, ...], Path],
    path: tuple[str, ...],
    errors: list[ConfigError],
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        here = (*path, key)
        existing = merged.get(key, _MISSING)
        if existing is _MISSING:
            merged[key] = value
            provenance[here] = source
        elif isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value, source, provenance, here, errors)
        else:
            origin = provenance.get(here)
            errors.append(
                ConfigError(
                    code="DUPLICATE_KEY",
                    message=f"'{_join_path(here)}' is defined in more than one file",
                    path=_join_path(here),
                    hint=(
                        f"Already set in {origin}; redefined in {source}"
                        if origin
                        else f"Redefined in {source}"
                    ),
                )
            )
    return merged


def _load_spec(path: Path) -> dict[str, Any]:
    manifest_path = path / MANIFEST_FILENAME if path.is_dir() else path
    if path.is_dir() and not manifest_path.is_file():
        raise ConfigErrors(
            [
                ConfigError(
                    code="MANIFEST_NOT_FOUND",
                    message=f"No {MANIFEST_FILENAME} found in spec directory",
                    path="$",
                    hint=f"Create {manifest_path}",
                )
            ]
        )

    root = _ensure_dict(_load_yaml(manifest_path), manifest_path)
    includes = root.get("include")
    if includes is None:
        return root
    if not isinstance(includes, list) or not all(isinstance(p, str) for p in includes):
        raise ConfigErrors(
            [
                ConfigError(
                    code="INCLUDE_INVALID",
                    message="'include' must be a list of glob patterns",
                    path="include",
                )
            ]
        )

    base_dir = manifest_path.parent
    errors: list[ConfigError] = []
    provenance: dict[tuple[str, ...], Path] = {}
    merged: dict[str, Any] = {}
    for pattern in includes:
        matches = sorted(base_dir.glob(pattern))
        if not matches:
            errors.append(
                ConfigError(
                    code="INCLUDE_NO_MATCH",
                    message=f"Include pattern '{pattern}' matched no files",
                    path=pattern,
                    hint="Patterns are resolved relative to the manifest",
                )
            )
            continue
        for match in matches:
            fragment = _ensure_dict(_load_yaml(match), match)
            merged = _deep_merge(merged, fragment, match, provenance, (), errors)

    overlay = {key: value for key, value in root.items() if key != "include"}
    merged = _deep_merge(merged, overlay, manifest_path, provenance, (), errors)

    if errors:
        raise ConfigErrors(errors)
    return merged


def _load_schema(schema_file: Path) -> dict[str, Any]:
    try:
        with schema_file.open("r", encoding="utf-8") as file:
            schema = yaml.safe_load(file)
    except (OSError, yaml.YAMLError) as error:
        raise ConfigErrors(
            [
                ConfigError(
                    code="SCHEMA_LOAD_ERROR",
                    message=str(error),
                    path="$",
                    hint="Provide a readable schema file",
                )
            ]
        ) from error
    if not isinstance(schema, dict):
        raise ConfigErrors(
            [
                ConfigError(
                    code="SCHEMA_LOAD_ERROR",
                    message="Schema root must be an object",
                    path="$",
                )
            ]
        )
    return schema


def _coerce_for_validation(node: Any) -> Any:
    """Replace EnvRef objects with placeholder strings for schema validation."""
    if isinstance(node, EnvRef):
        return node.default if node.default is not None else ""
    if isinstance(node, dict):
        return {k: _coerce_for_validation(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_coerce_for_validation(item) for item in node]
    return node


def _validate_schema(config: Any, schema: dict[str, Any]) -> list[ConfigError]:
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(_coerce_for_validation(config)),
        key=lambda item: (item.json_path, item.message),
    )
    return [
        ConfigError(
            code="SCHEMA_VALIDATION_ERROR",
            message=error.message,
            path=_join_path(tuple(str(part) for part in error.path)),
        )
        for error in errors
    ]


_VERSION_SCHEMA_MAP: dict[str, str] = {
    "0.1": "yaml-spec-v0.1.schema.json",
    "0.2": "yaml-spec-v0.2.schema.json",
}


def _resolve_schema_path(
    version: str, explicit_schema: str | Path | None
) -> Path:
    if explicit_schema is not None:
        return Path(explicit_schema)
    schema_name = _VERSION_SCHEMA_MAP.get(version)
    if schema_name is None:
        raise ConfigErrors(
            [
                ConfigError(
                    code="UNSUPPORTED_VERSION",
                    message=f"No built-in schema for version '{version}'",
                    path="version",
                    hint=f"Supported versions: {', '.join(sorted(_VERSION_SCHEMA_MAP))}",
                )
            ]
        )
    return Path(__file__).parent / "schemas" / schema_name


def load_and_generate_ir(
    yaml_file: str | Path, schema_file: str | Path | None = None
) -> ParseResult:
    yaml_path = Path(yaml_file)

    raw_config = _load_spec(yaml_path)

    interpolation_errors: list[ConfigError] = []
    resolved = _resolve_interpolation(raw_config, tuple(), interpolation_errors)
    if interpolation_errors:
        raise ConfigErrors(interpolation_errors)

    version = str(resolved.get("version", "0.1"))

    if version == "0.2":
        from .transformers.shape_validation import validate_spec_shape
        shape_errors = validate_spec_shape(resolved)
        if shape_errors:
            raise ConfigErrors(shape_errors)

        from .transformers.name_validation import validate_spec_names
        name_errors = validate_spec_names(resolved)
        if name_errors:
            raise ConfigErrors(name_errors)

        from .transformers.constraint_validation import validate_spec_constraints
        constraint_errors = validate_spec_constraints(resolved)
        if constraint_errors:
            raise ConfigErrors(constraint_errors)

        from .transformers.access_validation import validate_spec_access
        access_errors = validate_spec_access(resolved)
        if access_errors:
            raise ConfigErrors(access_errors)

        from .transformers.auth_validation import validate_spec_auth
        auth_errors = validate_spec_auth(resolved)
        if auth_errors:
            raise ConfigErrors(auth_errors)

        from .desugar import desugar_v02
        resolved = desugar_v02(resolved)

        from .transformers.path_validation import validate_spec_paths
        path_errors = validate_spec_paths(resolved)
        if path_errors:
            raise ConfigErrors(path_errors)

    ui_block = resolved.get("ui", None)

    schema_path = _resolve_schema_path(version, schema_file)

    schema = _load_schema(schema_path)

    config_for_validation = {k: v for k, v in resolved.items() if k != "ui"}
    schema_errors = _validate_schema(config_for_validation, schema)
    if schema_errors:
        raise ConfigErrors(schema_errors)

    from .transformers.registry import transform_config

    return ParseResult(ir=transform_config(resolved), ui_block=ui_block)
