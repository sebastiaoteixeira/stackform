"""File datastore binding, file-field IR and derived file routes.

Limits resolve at parse time, most specific first: the field, then the bound
file datastore's ``files:``, then ``api.files``, then the built-in defaults.
Sizes are bytes or ``<number><unit>`` with binary, case-insensitive units
(``KB`` = 1024, ``MB`` = 1024², ``GB`` = 1024³), floored to whole bytes.
"""

import math
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import Any

from yaml_api_generator.ir import (
    DEFAULT_FILE_MAX_SIZE,
    DEFAULT_MAX_FILES,
    IRAccessRule,
    IRCollection,
    IRFileField,
    IRFileLimits,
    IRFileRoute,
    IRFileStore,
    IRRepository,
    IRRoute,
)
from yaml_api_generator.ir.when import (
    And,
    Equals,
    FieldRef,
    In,
    Not,
    NotEquals,
    NotIn,
    Or,
    WhenExpr,
)
from yaml_api_generator.parsers.errors import ConfigError
from yaml_api_generator.parsers.transformers.file_validation import file_config

_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmg]?b)?\s*$", re.IGNORECASE)
_UNITS = {"": 1, "b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3}


def parse_size(value: Any, path: str) -> tuple[int | None, list[ConfigError]]:
    """Parse a byte count or a ``10MB``-style size into a positive number of bytes."""
    match = None if isinstance(value, bool) else _SIZE.match(str(value))
    size = math.floor(float(match[1]) * _UNITS[(match[2] or "").lower()]) if match else 0
    if size >= 1:
        return size, []
    return None, [ConfigError(
        code="FILE_SIZE_INVALID",
        message=f"maxSize {value!r} is not a positive size",
        path=path,
        hint="Use a byte count or a size such as 512KB, 10MB or 1GB",
    )]


@dataclass(frozen=True)
class LimitLayer:
    """One level of file limits; None means the level leaves that limit unset."""

    max_size: int | None = None
    types: tuple[str, ...] | None = None

    @classmethod
    def parse(cls, raw: Any, path: str) -> tuple["LimitLayer", list[ConfigError]]:
        if not isinstance(raw, dict):
            return cls(), []
        max_size, errors = (
            (None, []) if raw.get("maxSize") is None
            else parse_size(raw["maxSize"], f"{path}.maxSize")
        )
        types = raw.get("types")
        return cls(
            max_size=max_size,
            types=None if types is None else tuple(dict.fromkeys(t.lower() for t in types)),
        ), errors

    def over(self, lower: "LimitLayer") -> "LimitLayer":
        return LimitLayer(
            max_size=lower.max_size if self.max_size is None else self.max_size,
            types=lower.types if self.types is None else self.types,
        )

    def limits(self) -> IRFileLimits:
        return IRFileLimits(
            max_size=self.max_size or DEFAULT_FILE_MAX_SIZE,
            types=self.types or (),
        )


@dataclass(frozen=True)
class FileStoreRegistry:
    """Declared file datastores and the limits each contributes."""

    stores: dict[str, IRFileStore]
    default: str | None
    record_names: frozenset[str]
    layers: dict[str, LimitLayer]

    @classmethod
    def from_spec(
        cls,
        resolved: dict[str, Any],
        stores: dict[str, IRFileStore],
        default: str | None,
        record_names: set[str],
    ) -> "FileStoreRegistry":
        raw = resolved.get("datastores") or {}
        return cls(
            stores=stores,
            default=default,
            record_names=frozenset(record_names),
            layers={name: LimitLayer.parse(raw[name].get("files"), "")[0] for name in stores},
        )

    def resolve(
        self, repo_name: str, declared: Any, needed: bool
    ) -> tuple[str | None, ConfigError | None]:
        """Resolve a repository's ``files:`` binding; ``needed`` when its entity has file fields."""
        path = f"repositories.{repo_name}.files"
        if declared is None:
            if needed and not self.stores:
                return None, ConfigError(
                    code="FILE_DATASTORE_REQUIRED",
                    message=f"Repository '{repo_name}' has file fields but no file datastore is declared",
                    path=path,
                    hint="Declare a datastore with 'type: filesystem' or 'type: s3'",
                )
            if needed and self.default is None:
                return None, ConfigError(
                    code="FILE_DATASTORE_NO_DEFAULT",
                    message="Multiple file datastores declared but none marked 'default: true'",
                    path=path,
                    hint="Mark one file datastore 'default: true' or set 'files:' on this repository",
                )
            return self.default, None
        if declared in self.record_names:
            return None, ConfigError(
                code="DATASTORE_NOT_FILE",
                message=f"Repository '{repo_name}' binds record datastore '{declared}' as its file datastore",
                path=path,
                hint="Reference a datastore with 'type: filesystem' or 'type: s3'",
            )
        if declared not in self.stores:
            return None, ConfigError(
                code="FILE_DATASTORE_UNKNOWN_REFERENCE",
                message=f"Repository '{repo_name}' references unknown file datastore '{declared}'",
                path=path,
            )
        return declared, None


class FileTransformer:
    """Binds repositories to file datastores and derives the file-serving routes."""

    def bind(
        self,
        resolved: dict[str, Any],
        collections: dict[str, IRCollection],
        repositories: dict[str, IRRepository],
        registry: FileStoreRegistry,
    ) -> tuple[dict[str, IRCollection], dict[str, IRRepository], list[ConfigError]]:
        api_files = (resolved.get("api") or {}).get("files") or {}
        api_layer, errors = LimitLayer.parse(api_files, "api.files")
        max_files = api_files.get("maxFiles") or DEFAULT_MAX_FILES
        collections, repositories = dict(collections), dict(repositories)

        for repo_name, repo_cfg in (resolved.get("repositories") or {}).items():
            if not isinstance(repo_cfg, dict):
                continue
            collection = collections.get(repo_name)
            fields = {
                name: cfg for name, cfg in (collection.fields if collection else {}).items()
                if file_config(cfg) is not None
            }
            store, error = registry.resolve(repo_name, repo_cfg.get("files"), bool(fields))
            if error is not None:
                errors.append(error)
                continue
            if repo_name in repositories:
                repositories[repo_name] = replace(repositories[repo_name], files=store)
            if collection is None or store is None:
                continue
            layer = registry.layers[store].over(api_layer)
            files: dict[str, IRFileField] = {}
            for name, cfg in fields.items():
                files[name], field_errors = _file_field(
                    name, cfg, store, layer, max_files,
                    f"entities.{collection.entity_name}.fields.{name}",
                )
                errors.extend(field_errors)
            collections[repo_name] = replace(collection, files=files, file_store=store)

        return collections, repositories, errors

    def derive(
        self, collections: dict[str, IRCollection], routes: list[IRRoute]
    ) -> tuple[tuple[IRFileRoute, ...], list[ConfigError]]:
        """Derive file routes from get/update routes and reject file-field comparisons."""
        declared = {(route.method.upper(), route.path) for route in routes}
        file_routes: list[IRFileRoute] = []
        errors: list[ConfigError] = []
        for route in routes:
            collection = collections.get(route.collection) if route.collection else None
            errors.extend(_comparison_errors(route, collections))
            derive = _DERIVATIONS.get(route.operation)
            if route.handler is not None or derive is None or not (collection and collection.files):
                continue
            if "{fileId}" in route.path:
                errors.append(_route_conflict(
                    route, "source path already declares a '{fileId}' parameter"
                ))
                continue
            for field in collection.files.values():
                for action, method, item in derive(field):
                    path = f"{route.path}/files/{field.name}" + ("/{fileId}" if item else "")
                    if (method, path) in declared:
                        errors.append(_route_conflict(
                            route, f"derived route {method} {path} collides with a declared route"
                        ))
                        continue
                    file_routes.append(IRFileRoute(
                        action=action, method=method, path=path,
                        collection=route.collection, field=field.name, item=item, source=route,
                    ))
        return tuple(file_routes), errors


def _file_field(
    name: str,
    cfg: dict[str, Any],
    store: str,
    inherited: LimitLayer,
    max_files: int,
    path: str,
) -> tuple[IRFileField, list[ConfigError]]:
    spec = file_config(cfg)
    multiple = spec is not cfg
    own, errors = LimitLayer.parse(spec, f"{path}.items" if multiple else path)
    return IRFileField(
        name=name,
        store=store,
        limits=own.over(inherited).limits(),
        required=bool(cfg.get("required")),
        readonly=bool(cfg.get("readonly")),
        multiple=multiple,
        max_items=cfg.get("maxItems", max_files) if multiple else None,
        disposition=spec.get("disposition", "attachment"),
    ), errors


_Derived = Iterator[tuple[str, str, bool]]


def _download_routes(field: IRFileField) -> _Derived:
    yield "download", "GET", field.multiple


def _update_routes(field: IRFileField) -> _Derived:
    if field.readonly:
        return
    yield "replace", "PUT", False
    if field.multiple:
        yield "replace", "PUT", True
    yield "remove", "DELETE", field.multiple


_DERIVATIONS: dict[str, Callable[[IRFileField], _Derived]] = {
    "get": _download_routes,
    "update": _update_routes,
}


def _route_conflict(route: IRRoute, reason: str) -> ConfigError:
    return ConfigError(
        code="FILE_ROUTE_CONFLICT",
        message=f"File routes of {route.method} {route.path} cannot be derived: {reason}",
        path=f"{route.method} {route.path}",
        hint="Rename the declared route or its path parameter",
    )


def _compared_refs(expr: WhenExpr | None) -> Iterator[FieldRef]:
    match expr:
        case Equals(left, right) | NotEquals(left, right):
            yield from (ref for ref in (left, right) if isinstance(ref, FieldRef))
        case In(left, _) | NotIn(left, _) if isinstance(left, FieldRef):
            yield left
        case And(left, right) | Or(left, right):
            yield from _compared_refs(left)
            yield from _compared_refs(right)
        case Not(operand):
            yield from _compared_refs(operand)


def _file_fields_by_symbol(
    route: IRRoute, rule: IRAccessRule, collections: dict[str, IRCollection]
) -> dict[str, dict[str, IRFileField]]:
    symbols = {
        "document": route.collection,
        **{name: b.collection_name for name, b in rule.identity_symbols.items()},
        **{name: b.collection for name, b in rule.document_symbols.items()},
    }
    return {
        symbol: collections[collection].files
        for symbol, collection in symbols.items()
        if collection in collections
    }


def _comparison_errors(route: IRRoute, collections: dict[str, IRCollection]) -> list[ConfigError]:
    errors: list[ConfigError] = []
    for index, rule in enumerate(route.access_rules or ()):
        files = _file_fields_by_symbol(route, rule, collections)
        base = f"{route.method} {route.path} access[{index}]"
        errors.extend(
            _not_comparable(f"{ref.root}.{ref.path[0]}", f"{base}.when")
            for ref in _compared_refs(rule.when)
            if ref.path and ref.path[0] in files.get(ref.root, ())
        )
        errors.extend(
            _not_comparable(f"{name}.{conjunct.field}", f"{base}.given.{name}")
            for name, binding in rule.document_symbols.items()
            for conjunct in binding.where
            if conjunct.field in files.get(name, ())
        )
    return errors


def _not_comparable(reference: str, path: str) -> ConfigError:
    return ConfigError(
        code="FILE_FIELD_NOT_COMPARABLE",
        message=f"file field '{reference}' cannot be compared",
        path=path,
        hint="Compare a non-file field; file values are upload metadata",
    )
