"""Datastore registry parsing for v0.2 specs.

Parses the optional top-level `datastores:` block into IR datastore objects.
Entries belong to one of two families: record datastores (mongodb, postgres)
back repositories, file datastores (filesystem, s3) hold uploaded bytes. Each
family resolves its own default. When no record datastore is declared, a single
default one is synthesized from the legacy `mongo:` block so existing specs are
unaffected.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from yaml_api_generator.ir import (
    IRDatastore,
    IRFileLimits,
    IRFileStore,
    IRFilesystemStore,
    IRMongo,
    IRPostgres,
    IRS3Store,
)
from yaml_api_generator.parsers.yaml_parser import ConfigError

from .file_transformer import LimitLayer

DEFAULT_DATASTORE = "default"

_Built = tuple[Any, list[ConfigError]]


@dataclass(frozen=True)
class _Family:
    name: str
    multiple_defaults_code: str

    def parse(self, raw: dict[str, Any]) -> tuple[dict[str, Any], str | None, list[ConfigError]]:
        """Build this family's entries and resolve its default (None when ambiguous or absent)."""
        built: dict[str, Any] = {}
        errors: list[ConfigError] = []
        defaults: list[str] = []
        for name, cfg in raw.items():
            kind = _kind(cfg)
            if kind is None or kind.family is not self:
                continue
            entry, entry_errors = kind.create(name, cfg)
            errors.extend(entry_errors)
            if entry is not None:
                built[name] = entry
            if cfg.get("default") is True:
                defaults.append(name)

        errors.extend(
            ConfigError(
                code=self.multiple_defaults_code,
                message=f"Datastores '{defaults[0]}' and '{name}' both marked default",
                path=f"datastores.{name}.default",
            )
            for name in defaults[1:]
        )
        single = next(iter(built)) if len(built) == 1 else None
        return built, defaults[0] if defaults else single, errors


RECORD = _Family("record", "DATASTORE_MULTIPLE_DEFAULTS")
FILE = _Family("file", "FILE_DATASTORE_MULTIPLE_DEFAULTS")


@dataclass(frozen=True)
class _Kind:
    family: _Family
    build: Callable[[str, dict[str, Any]], _Built]
    label: str = ""
    required: str | None = None
    missing_code: str = ""

    def create(self, name: str, cfg: dict[str, Any]) -> _Built:
        if self.required is not None and cfg.get(self.required) is None:
            return None, [ConfigError(
                code=self.missing_code,
                message=f"{self.label} datastore '{name}' requires a '{self.required}'",
                path=f"datastores.{name}.{self.required}",
            )]
        return self.build(name, cfg)


def _file_limits(name: str, cfg: dict[str, Any]) -> tuple[IRFileLimits | None, list[ConfigError]]:
    layer, errors = LimitLayer.parse(cfg.get("files"), f"datastores.{name}.files")
    return (layer.limits() if "files" in cfg else None), errors


def _mongo(name: str, cfg: dict[str, Any]) -> _Built:
    return IRMongo(
        uri=cfg.get("uri", IRMongo.uri),
        database=cfg.get("database", IRMongo.database),
    ), []


def _postgres(name: str, cfg: dict[str, Any]) -> _Built:
    return IRPostgres(dsn=cfg["dsn"]), []


def _filesystem(name: str, cfg: dict[str, Any]) -> _Built:
    limits, errors = _file_limits(name, cfg)
    return IRFilesystemStore(path=cfg["path"], limits=limits), errors


def _s3(name: str, cfg: dict[str, Any]) -> _Built:
    limits, errors = _file_limits(name, cfg)
    return IRS3Store(
        bucket=cfg["bucket"],
        endpoint=cfg.get("endpoint"),
        region=cfg.get("region"),
        access_key=cfg.get("accessKey"),
        secret_key=cfg.get("secretKey"),
        prefix=cfg.get("prefix", ""),
        limits=limits,
    ), errors


_MONGO = _Kind(RECORD, _mongo)
_POSTGRES = _Kind(RECORD, _postgres, "Postgres", "dsn", "DATASTORE_MISSING_DSN")
_KINDS: dict[str | None, _Kind] = {
    None: _MONGO,
    "mongodb": _MONGO,
    "mongo": _MONGO,
    "postgres": _POSTGRES,
    "postgresql": _POSTGRES,
    "filesystem": _Kind(FILE, _filesystem, "Filesystem", "path", "DATASTORE_FILE_MISSING_PATH"),
    "s3": _Kind(FILE, _s3, "S3", "bucket", "DATASTORE_FILE_MISSING_BUCKET"),
}


def _kind(cfg: Any) -> _Kind | None:
    if not isinstance(cfg, dict):
        return None
    ds_type = cfg.get("type")
    return _KINDS.get(ds_type) if isinstance(ds_type, str | None) else None


def _invalid_entries(raw: dict[str, Any]) -> list[ConfigError]:
    return [
        ConfigError(
            code="DATASTORE_TYPE_UNKNOWN",
            message=f"Unknown datastore type '{cfg.get('type')}' for datastore '{name}'",
            path=f"datastores.{name}.type",
        ) if isinstance(cfg, dict) else ConfigError(
            code="DATASTORE_INVALID",
            message=f"Datastore '{name}' must be a mapping",
            path=f"datastores.{name}",
        )
        for name, cfg in raw.items()
        if _kind(cfg) is None
    ]


def parse_datastores(
    resolved: dict[str, Any],
) -> tuple[dict[str, IRDatastore], str, list[ConfigError]]:
    """Return (record datastores, default_name, errors) for a resolved spec."""
    raw = resolved.get("datastores") or {}
    errors = _invalid_entries(raw)
    datastores, default_name, family_errors = RECORD.parse(raw)
    errors.extend(family_errors)

    if not errors and not datastores:
        mongo = resolved.get("mongo", {}) or {}
        return {DEFAULT_DATASTORE: _mongo(DEFAULT_DATASTORE, mongo)[0]}, DEFAULT_DATASTORE, []

    if default_name is None and datastores:
        errors.append(ConfigError(
            code="DATASTORE_NO_DEFAULT",
            message="Multiple datastores declared but none marked 'default: true'",
            path="datastores",
        ))
    return datastores, default_name or DEFAULT_DATASTORE, errors


def parse_file_datastores(
    resolved: dict[str, Any],
) -> tuple[dict[str, IRFileStore], str | None, list[ConfigError]]:
    """Return (file datastores, default_name, errors); the default is None when ambiguous or absent."""
    return FILE.parse(resolved.get("datastores") or {})


def resolve_binding(
    repo_name: str,
    repo_cfg: dict[str, Any],
    valid_names: set[str],
    default_name: str,
    file_names: Collection[str] = frozenset(),
) -> tuple[str | None, ConfigError | None]:
    """Resolve and validate a repository's record datastore binding."""
    declared = repo_cfg.get("datastore")
    if declared is None:
        return default_name, None
    if declared in file_names:
        return None, ConfigError(
            code="DATASTORE_NOT_RECORD",
            message=(
                f"Repository '{repo_name}' binds file datastore '{declared}' as its "
                "record datastore"
            ),
            path=f"repositories.{repo_name}.datastore",
            hint=f"Use 'files: {declared}' and bind a mongodb or postgres datastore",
        )
    if declared not in valid_names:
        return None, ConfigError(
            code="DATASTORE_UNKNOWN_REFERENCE",
            message=f"Repository '{repo_name}' references unknown datastore '{declared}'",
            path=f"repositories.{repo_name}.datastore",
        )
    return declared, None
