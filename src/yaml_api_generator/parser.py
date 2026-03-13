import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft202012Validator

from .ir import (
    IRApi,
    IRCollection,
    IRDocument,
    IRIdentityCollection,
    IROperations,
    IRRoute,
)


OPERATION_NAMES = ("list", "get", "create", "update", "replace", "delete")
ROUTE_MAPPING: dict[str, tuple[str, str]] = {
    "list": ("GET", "/{collection}"),
    "get": ("GET", "/{collection}/{id}"),
    "create": ("POST", "/{collection}"),
    "update": ("PATCH", "/{collection}/{id}"),
    "replace": ("PUT", "/{collection}/{id}"),
    "delete": ("DELETE", "/{collection}/{id}"),
}
INTERPOLATION_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


@dataclass(frozen=True)
class ConfigError:
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


def _join_path(parts: tuple[str, ...]) -> str:
    return ".".join(parts) if parts else "$"


def _interpolate_string(
    value: str, path: tuple[str, ...], errors: list[ConfigError]
) -> str:
    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default = match.group(2)
        env_value = os.environ.get(var_name)
        if env_value is not None:
            return env_value
        if default is not None:
            return default

        errors.append(
            ConfigError(
                code="INTERPOLATION_MISSING_VAR",
                message=f"Environment variable '{var_name}' is required",
                path=_join_path(path),
                hint=f"Set {var_name} or use ${{{var_name}:-default}}",
            )
        )
        return match.group(0)

    return INTERPOLATION_PATTERN.sub(replace, value)


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


def _normalize_operations(
    global_defaults: dict[str, Any], collection_ops: dict[str, Any] | None
) -> IROperations:
    defaults = {name: True for name in OPERATION_NAMES}
    for name in OPERATION_NAMES:
        if name in global_defaults:
            defaults[name] = bool(global_defaults[name])
    if collection_ops:
        for name in OPERATION_NAMES:
            if name in collection_ops:
                defaults[name] = bool(collection_ops[name])
    return IROperations(**defaults)


def _extract_collection_id_field(
    collection_name: str,
    fields: dict[str, Any],
) -> tuple[str | None, list[ConfigError]]:
    id_fields = [
        field_name
        for field_name, field_config in fields.items()
        if isinstance(field_config, dict) and field_config.get("type") == "id"
    ]

    if len(id_fields) == 1:
        return id_fields[0], []

    if not id_fields:
        return (
            None,
            [
                ConfigError(
                    code="ID_FIELD_MISSING",
                    message="Collection must define exactly one field with type 'id'",
                    path=f"collections.{collection_name}.fields",
                )
            ],
        )

    return (
        None,
        [
            ConfigError(
                code="ID_FIELD_MULTIPLE",
                message="Collection must define exactly one field with type 'id'",
                path=f"collections.{collection_name}.fields",
                hint=f"Found multiple id fields: {', '.join(id_fields)}",
            )
        ],
    )


def _resolve_collection_id_format(
    collection_name: str,
    id_field: str,
    fields: dict[str, Any],
) -> tuple[str | None, list[ConfigError]]:
    field_config = fields.get(id_field)
    if not isinstance(field_config, dict):
        return (
            None,
            [
                ConfigError(
                    code="ID_FIELD_INVALID",
                    message="Collection id field configuration is invalid",
                    path=f"collections.{collection_name}.fields.{id_field}",
                )
            ],
        )

    raw_format = field_config.get("format")
    if raw_format is None:
        return "uuidv7", []

    if raw_format in {"uuidv7", "uuidv4"}:
        return str(raw_format), []

    return (
        None,
        [
            ConfigError(
                code="ID_FORMAT_INVALID",
                message="id field format must be uuidv7 or uuidv4",
                path=f"collections.{collection_name}.fields.{id_field}.format",
            )
        ],
    )


def _build_routes(collection: str, operations: IROperations) -> list[IRRoute]:
    op_map = operations.__dict__
    routes: list[IRRoute] = []
    for operation in OPERATION_NAMES:
        if not op_map[operation]:
            continue
        method, path_template = ROUTE_MAPPING[operation]
        routes.append(
            IRRoute(
                method=method,
                path=path_template.format(collection=collection, id="{id}"),
                operation=operation,
                collection=collection,
            )
        )
    return routes


def _is_operation_public(access_value: Any) -> bool | None:
    if access_value is None:
        return None
    if isinstance(access_value, str):
        normalized = access_value.strip().lower()
        if normalized == "public":
            return True
        if normalized == "authenticated":
            return False
        if normalized.startswith("identity:"):
            return False
        return None
    if not isinstance(access_value, list):
        return None

    saw_rule = False
    for rule in access_value:
        if not isinstance(rule, dict):
            continue

        principal = rule.get("principal")
        principal_type = ""
        if isinstance(principal, str):
            principal_normalized = principal.strip().lower()
            if principal_normalized.startswith("identity:"):
                principal_type = "identity"
            else:
                principal_type = principal_normalized
        if not principal_type:
            continue

        saw_rule = True
        if principal_type == "public":
            return True

    if saw_rule:
        return False
    return None


def _build_routes_with_access_policy(
    collection: str,
    operations: IROperations,
    collection_access: dict[str, Any],
) -> list[IRRoute]:
    op_map = operations.__dict__
    routes: list[IRRoute] = []
    for operation in OPERATION_NAMES:
        if not op_map[operation]:
            continue
        is_public = _is_operation_public(collection_access.get(operation))
        if is_public is None:
            is_public = True
        method, path_template = ROUTE_MAPPING[operation]
        routes.append(
            IRRoute(
                method=method,
                path=path_template.format(collection=collection, id="{id}"),
                operation=operation,
                collection=collection,
                is_public=is_public,
            )
        )
    return routes


def _normalize_auth_via(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return cast(list[str], list(value))
    return []


def _extract_identity_auth(
    collection_data: dict[str, Any],
) -> tuple[str | None, list[str]]:
    auth_data = collection_data.get("auth")
    if isinstance(auth_data, dict):
        return auth_data.get("identifier"), _normalize_auth_via(auth_data.get("via"))

    return None, []


def _validate_implicit_auth_fields(
    collections: dict[str, IRCollection],
    identity_collections: dict[str, IRIdentityCollection],
) -> list[ConfigError]:
    errors: list[ConfigError] = []
    for name, identity in identity_collections.items():
        if "password" not in identity.via:
            continue

        fields = collections[name].fields
        if "password" in fields:
            errors.append(
                ConfigError(
                    code="AUTH_PASSWORD_FIELD_FORBIDDEN",
                    message=(
                        "Password input is implicit when auth.via includes password"
                    ),
                    path=f"collections.{name}.fields.password",
                    hint="Remove the password field from YAML",
                )
            )
        if "passwordHash" in fields:
            errors.append(
                ConfigError(
                    code="AUTH_PASSWORD_HASH_FIELD_FORBIDDEN",
                    message=(
                        "passwordHash is implicit storage when auth.via includes password"
                    ),
                    path=f"collections.{name}.fields.passwordHash",
                    hint="Remove the passwordHash field from YAML",
                )
            )
    return errors


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


def _validate_schema(config: Any, schema: dict[str, Any]) -> list[ConfigError]:
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(config), key=lambda item: (item.json_path, item.message)
    )
    return [
        ConfigError(
            code="SCHEMA_VALIDATION_ERROR",
            message=error.message,
            path=_join_path(tuple(str(part) for part in error.path)),
        )
        for error in errors
    ]


def load_and_generate_ir(yaml_file: str | Path, schema_file: str | Path) -> IRDocument:
    yaml_path = Path(yaml_file)
    schema_path = Path(schema_file)

    raw_config = _load_yaml(yaml_path)
    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, dict):
        raise ConfigErrors(
            [
                ConfigError(
                    code="YAML_ROOT_INVALID",
                    message="Top-level YAML document must be an object",
                    path="$",
                )
            ]
        )

    interpolation_errors: list[ConfigError] = []
    resolved = _resolve_interpolation(raw_config, tuple(), interpolation_errors)
    if interpolation_errors:
        raise ConfigErrors(interpolation_errors)

    schema = _load_schema(schema_path)
    schema_errors = _validate_schema(resolved, schema)
    if schema_errors:
        raise ConfigErrors(schema_errors)

    api: dict[str, Any] = resolved.get("api", {})
    collections_data: dict[str, Any] = resolved["collections"]
    defaults = api.get("operations", {}).get("defaults", {})

    collections: dict[str, IRCollection] = {}
    collection_access_policies: dict[str, dict[str, Any]] = {}
    id_field_errors: list[ConfigError] = []
    for name, collection_data in collections_data.items():
        collection_type = str(collection_data.get("type", "base"))
        operations = _normalize_operations(defaults, collection_data.get("operations"))
        fields = cast(dict[str, Any], collection_data["fields"])
        id_field, errors = _extract_collection_id_field(name, fields)
        id_field_errors.extend(errors)

        id_format: str | None = None
        if id_field is not None:
            id_format, format_errors = _resolve_collection_id_format(
                name, id_field, fields
            )
            id_field_errors.extend(format_errors)

        raw_access = collection_data.get("access")
        collection_access_policies[name] = (
            raw_access if isinstance(raw_access, dict) else {}
        )

        if id_field is None or id_format is None:
            continue

        collections[name] = IRCollection(
            name=name,
            type=collection_type,
            idField=id_field,
            idFormat=id_format,
            fields=fields,
            operations=operations,
        )

    if id_field_errors:
        raise ConfigErrors(id_field_errors)

    identity_collections: dict[str, IRIdentityCollection] = {}
    for name, collection in collections.items():
        if collection.type != "auth":
            continue
        collection_data = collections_data.get(name, {})
        identifier, via = _extract_identity_auth(collection_data)
        identity_collections[name] = IRIdentityCollection(
            name=name,
            identifier=identifier,
            via=via,
        )

    implicit_field_errors = _validate_implicit_auth_fields(
        collections,
        identity_collections,
    )
    if implicit_field_errors:
        raise ConfigErrors(implicit_field_errors)

    routes: list[IRRoute] = []
    for name, collection in collections.items():
        routes.extend(
            _build_routes_with_access_policy(
                name,
                collection.operations,
                collection_access_policies.get(name, {}),
            )
        )

    for name, identity in identity_collections.items():
        if "password" in identity.via:
            routes.append(
                IRRoute(
                    method="POST",
                    path=f"/{name}/login",
                    operation="login",
                    collection=name,
                    is_public=True,
                )
            )

    return IRDocument(
        version=str(resolved["version"]),
        api=IRApi(basePath=api.get("basePath", "/api"), version=api.get("version")),
        collections=collections,
        routes=routes,
        identityCollections=identity_collections,
    )
