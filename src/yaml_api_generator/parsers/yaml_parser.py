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
- The resolved spec is schema-validated before any other check runs
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from referencing import Registry, Resource

from ..ir import IRDocument
from .errors import ConfigError, ConfigErrors, join_path
from .template_loader import Manifest

INTERPOLATION_PATTERN = re.compile(r"\$\{([^{}]*?)\}")
INTERPOLATION_TOKEN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?::-(.*))?$", re.DOTALL)
INTERPOLATION_MAX_DEPTH = 10
_BRACE_ESCAPES = ((r"\{", "\x00"), (r"\}", "\x01"))
SCHEMA_DIR = Path(__file__).parent / "schemas"
SCHEMA_REGISTRY: Registry = Registry().with_resources(
    (path.name, Resource.from_contents(json.loads(path.read_text(encoding="utf-8"))))
    for path in SCHEMA_DIR.glob("*.schema.json")
)

__all__ = ["ConfigError", "ConfigErrors", "ParseResult", "load_and_generate_ir"]


@dataclass(frozen=True)
class ParseResult:
    ir: IRDocument
    ui_block: dict | None = None
    warnings: tuple[ConfigError, ...] = field(default_factory=tuple)


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
                    path=join_path(path),
                    hint="Use ${VAR_NAME} or ${VAR_NAME:-default}",
                )
            )
        else:
            var_name = token.group(1)
            errors.append(
                ConfigError(
                    code="INTERPOLATION_MISSING_VAR",
                    message=f"Environment variable '{var_name}' is required",
                    path=join_path(path),
                    hint=f"Set {var_name} or use ${{{var_name}:-default}}",
                )
            )

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
        return _interpolate_string(node, path, errors)
    return node


def _load_spec(path: Path) -> dict[str, Any]:
    return Manifest.discover(path).load()


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


def validate_schema(config: Any, schema: dict[str, Any]) -> list[ConfigError]:
    validator = Draft202012Validator(schema, registry=SCHEMA_REGISTRY)
    errors = sorted(
        validator.iter_errors(config),
        key=lambda item: (item.json_path, item.message),
    )
    return [
        ConfigError(
            code="SCHEMA_VALIDATION_ERROR",
            message=best_match([error]).message,
            path=join_path(tuple(str(part) for part in error.path)),
        )
        for error in errors
    ]


_VERSION_SCHEMA_MAP: dict[str, str] = {
    "0.1": "yaml-spec-v0.1.schema.json",
    "0.2": "yaml-spec-v0.2.schema.json",
    "0.3": "yaml-spec-v0.3.schema.json",
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
    return SCHEMA_DIR / schema_name


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
    schema_errors = validate_schema(
        resolved, _load_schema(_resolve_schema_path(version, schema_file))
    )
    if schema_errors:
        raise ConfigErrors(schema_errors)

    ui_block = resolved.get("ui")
    trust_warnings: tuple[ConfigError, ...] = ()
    access_warnings: tuple[ConfigError, ...] = ()

    if version in ("0.2", "0.3"):
        from .transformers.name_validation import validate_spec_names
        name_errors = validate_spec_names(resolved)
        if name_errors:
            raise ConfigErrors(name_errors)

    from .transformers.ref_validation import validate_spec_refs
    ref_errors = validate_spec_refs(resolved)
    if ref_errors:
        raise ConfigErrors(ref_errors)

    from .transformers.constraint_validation import validate_spec_constraints
    constraint_errors = validate_spec_constraints(resolved)
    if constraint_errors:
        raise ConfigErrors(constraint_errors)

    from .transformers.field_defaults import canonicalize_defaults
    canonicalize_defaults(resolved)

    if version in ("0.2", "0.3"):
        from .transformers.file_validation import validate_spec_files
        file_errors = validate_spec_files(resolved)
        if file_errors:
            raise ConfigErrors(file_errors)

        from .transformers.dto_validation import validate_spec_dtos
        dto_errors = validate_spec_dtos(resolved)
        if dto_errors:
            raise ConfigErrors(dto_errors)

        from .transformers.policy_validation import validate_spec_policies
        policy_errors = validate_spec_policies(resolved)
        if policy_errors:
            raise ConfigErrors(policy_errors)

        from .transformers.access_validation import validate_spec_access, warn_public_routes
        access_errors = validate_spec_access(resolved)
        if access_errors:
            raise ConfigErrors(access_errors)
        access_warnings = tuple(warn_public_routes(resolved))

        if version == "0.3":
            from .transformers.symbol_validation import validate_spec_symbols
            symbol_errors = validate_spec_symbols(resolved)
            if symbol_errors:
                raise ConfigErrors(symbol_errors)

        from .transformers.auth_validation import validate_spec_auth
        auth_errors = validate_spec_auth(resolved)
        if auth_errors:
            raise ConfigErrors(auth_errors)

        from .transformers.binding_validation import validate_spec_bindings
        binding_errors = validate_spec_bindings(resolved)
        if binding_errors:
            raise ConfigErrors(binding_errors)

        from .transformers.trust_validation import validate_spec_trust
        trust_warnings = tuple(validate_spec_trust(resolved))

        from .desugar import desugar_v02
        resolved = desugar_v02(resolved)

        from .transformers.path_validation import validate_spec_paths
        path_errors = validate_spec_paths(resolved)
        if path_errors:
            raise ConfigErrors(path_errors)

        from .transformers.request_path_validation import validate_spec_request_paths
        request_path_errors = validate_spec_request_paths(resolved)
        if request_path_errors:
            raise ConfigErrors(request_path_errors)

    from .transformers.registry import transform_config

    return ParseResult(
        ir=transform_config(resolved, yaml_path.parent),
        ui_block=ui_block,
        warnings=trust_warnings + access_warnings,
    )
