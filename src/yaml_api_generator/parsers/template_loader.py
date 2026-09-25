"""Cross-file YAML anchor sharing for the ``templates:`` and ``include:`` manifest keys.

PyYAML's ``Composer`` resets its anchor table at the end of every document, so
a plain ``yaml.safe_load`` can never resolve an alias defined in another file.
``_SeededSafeLoader`` re-seeds that table from an :class:`AnchorPool` collected
across files, so later files resolve both ``*name`` and ``<<: *name`` against
anchors an earlier file defined. ``Manifest`` owns the ``api.yaml`` lifecycle
built on top of it: discovering the manifest, resolving its ``templates:``/
``include:`` globs, and merging every matched file plus the manifest's own
overlay body into one document.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import yaml
from yaml.events import (
    AliasEvent,
    MappingEndEvent,
    MappingStartEvent,
    SequenceEndEvent,
    SequenceStartEvent,
    StreamEndEvent,
)
from yaml.nodes import Node

from .errors import ConfigError, ConfigErrors, format_location, join_path

_MANIFEST_FILENAME = "api.yaml"
_MANIFEST_ONLY_KEYS = ("include", "templates")
_MISSING = object()


class Anchor(NamedTuple):
    """One composed anchor, tagged with the file that defined it."""

    node: Node
    origin: str


@dataclass(frozen=True)
class AnchorPool:
    """Anchors composed so far, keyed by name."""

    anchors: dict[str, Anchor]

    @classmethod
    def empty(cls) -> AnchorPool:
        return cls({})

    def extend(self, other: AnchorPool) -> AnchorPool:
        return AnchorPool({**self.anchors, **other.anchors})


class _SeededSafeLoader(yaml.SafeLoader):
    """SafeLoader that resolves aliases against a pool composed from other files.

    Only the anchor table's *starting* contents differ from vanilla
    ``SafeLoader``; single-file behaviour (local anchors, ``<<`` merge keys,
    self-contained aliases) is otherwise unchanged. Alias/anchor problems are
    collected into ``errors`` rather than raised, so every problem in a file
    is reported together instead of stopping at the first one.
    """

    def __init__(self, stream: Any, pool: AnchorPool, source: Path) -> None:
        super().__init__(stream)
        self._pool = pool
        self._source = source
        self.errors: list[ConfigError] = []
        # Anchors this document itself defines, keyed the same as AnchorPool
        # -- Composer.compose_document clears self.anchors on return, so this
        # is the only place they survive for new_pool().
        self._defined: dict[str, Anchor] = {}
        # Anchors whose node is still being composed, i.e. between the point
        # _register_anchor records them and the point it returns -- an alias
        # to one of these mid-flight anchors is a self-recursive node such as
        # ``&a [*a]``, which PyYAML would otherwise happily construct into a
        # Python list containing itself.
        self._composing: set[str] = set()

    def compose_document(self) -> Node:
        self.anchors = {name: anchor.node for name, anchor in self._pool.anchors.items()}
        node = super().compose_document()
        assert node is not None  # a called compose_document always composes a root
        return node

    def compose_node(self, parent: Node | None, index: Any) -> Node:
        if self.check_event(AliasEvent):
            return self._resolve_alias()
        return self._register_anchor(parent, index)

    def _resolve_alias(self) -> Node:
        event = self.get_event()
        assert isinstance(event, AliasEvent)
        anchor = event.anchor
        if anchor in self._composing:
            self.errors.append(
                ConfigError(
                    code="TEMPLATE_CYCLE",
                    message=f"Anchor '&{anchor}' cannot reference itself",
                    path=join_path(()),
                    location=format_location(self._source, event.start_mark),
                    hint="Self-recursive anchors are not supported",
                )
            )
        elif anchor not in self.anchors:
            self.errors.append(self._unknown_alias_error(anchor, event))
        else:
            return self.anchors[anchor]
        return _placeholder(event)

    def _register_anchor(self, parent: Node | None, index: Any) -> Node:
        event = self.peek_event()
        anchor = event.anchor
        if anchor in self.anchors:
            self.errors.append(
                ConfigError(
                    code="TEMPLATE_DUPLICATE",
                    message=f"Anchor '&{anchor}' is already defined",
                    path=join_path(()),
                    location=format_location(self._source, event.start_mark),
                    hint=f"Already anchored in {self._origin(anchor)}",
                )
            )
            # Still compose the node's children so problems inside them are reported too
            event.anchor = anchor = None
        if anchor is None:
            return self._compose_unanchored(parent, index)
        self._composing.add(anchor)
        try:
            node = self._compose_unanchored(parent, index)
        finally:
            self._composing.discard(anchor)
        self._defined[anchor] = Anchor(node, format_location(self._source, event.start_mark))
        return node

    def _compose_unanchored(self, parent: Node | None, index: Any) -> Node:
        node = super().compose_node(parent, index)
        assert node is not None  # a non-alias event always composes a node
        return node

    def _unknown_alias_error(self, anchor: str, event: AliasEvent) -> ConfigError:
        suggestion = difflib.get_close_matches(anchor, sorted(self.anchors), n=1)
        hint = f"Did you mean '{suggestion[0]}'?" if suggestion else None
        return ConfigError(
            code="TEMPLATE_UNKNOWN",
            message=f"Alias '*{anchor}' references an anchor that is not defined",
            path=join_path(()),
            location=format_location(self._source, event.start_mark),
            hint=hint,
        )

    def _origin(self, anchor: str) -> str:
        if anchor in self._defined:
            return self._defined[anchor].origin
        return self._pool.anchors[anchor].origin

    def new_pool(self) -> AnchorPool:
        """This document's own contribution to the pool: anchors it newly defined."""
        return AnchorPool(dict(self._defined))


def _placeholder(event: AliasEvent) -> Node:
    """A tagless null node standing in for an alias/cycle error's target.

    Composition must still return *something* so the enclosing sequence or
    mapping can finish building; the real failure is already queued in
    ``errors``, and ``load_file`` never constructs a document once ``errors``
    is non-empty, so this value is never actually seen by calling code.
    """
    return yaml.ScalarNode("tag:yaml.org,2002:null", "", event.start_mark, event.end_mark)


def _parse_error(source: Path, error: yaml.YAMLError) -> ConfigErrors:
    mark = getattr(error, "problem_mark", None)
    location = format_location(source, mark) if mark is not None else str(source)
    return ConfigErrors(
        [ConfigError(code="YAML_PARSE_ERROR", message=str(error), path=join_path(()), location=location)]
    )


def load_file(source: Path, pool: AnchorPool) -> tuple[Any, AnchorPool]:
    """Parse one YAML file with ``pool``'s anchors resolvable by alias or merge key.

    Composing happens fully before any construction is attempted, so an
    alias/anchor error never risks tripping a merge-key construction crash on
    its way to being reported. Returns the constructed document alongside a
    pool extended with any anchors this file defined; callers that must not
    let a file's anchors leak (``include:`` fragments, the manifest overlay)
    discard the returned pool instead of threading it into the next call.
    """
    with source.open("r", encoding="utf-8") as stream:
        loader = _SeededSafeLoader(stream, pool, source)
        try:
            node = loader.get_single_node()
            if loader.errors:
                raise ConfigErrors(loader.errors)
            data = loader.construct_document(node) if node is not None else None
        except yaml.YAMLError as error:
            raise _parse_error(source, error) from error
        finally:
            loader.dispose()
    return data, pool.extend(loader.new_pool())


def _compose(loader: yaml.SafeLoader) -> Node:
    """``compose_node`` narrowed to non-``None``: only empty at stream end, never mid-document."""
    node = loader.compose_node(None, None)  # pyright: ignore[reportArgumentType]  # stub types index as int; None is the root
    assert node is not None
    return node


def _peek_globs(path: Path) -> tuple[Any, Any]:
    """Read the ``templates:``/``include:`` values without composing anything else.

    The manifest's own body may alias an anchor defined in a ``templates:``
    file, which does not exist yet at this point -- so nothing else in the
    document may be composed here. Walking the raw event stream and skipping
    every other key avoids ever resolving such an alias prematurely; a plain
    (unseeded) loader is enough for the two glob-list keys themselves, since
    they are never expected to hold aliases of their own.
    """
    with path.open("r", encoding="utf-8") as stream:
        loader = yaml.SafeLoader(stream)
        try:
            loader.get_event()  # StreamStartEvent
            if loader.check_event(StreamEndEvent):
                return None, None
            loader.get_event()  # DocumentStartEvent
            if not loader.check_event(MappingStartEvent):
                return None, None  # non-mapping root; _ensure_dict reports this later
            loader.get_event()  # MappingStartEvent
            templates: Any = None
            include: Any = None
            while not loader.check_event(MappingEndEvent):
                key = loader.construct_object(_compose(loader))
                if key == "templates":
                    templates = loader.construct_object(_compose(loader), deep=True)
                elif key == "include":
                    include = loader.construct_object(_compose(loader), deep=True)
                else:
                    _skip_value(loader)
            return templates, include
        except yaml.YAMLError as error:
            raise _parse_error(path, error) from error
        finally:
            loader.dispose()


def _skip_value(loader: yaml.SafeLoader) -> None:
    """Advance past one value's events without composing or constructing it."""
    depth = 0
    while True:
        event = loader.get_event()
        if isinstance(event, (MappingStartEvent, SequenceStartEvent)):
            depth += 1
        elif isinstance(event, (MappingEndEvent, SequenceEndEvent)):
            depth -= 1
        if depth == 0:
            return


def _ensure_dict(content: Any, source: Path) -> dict[str, Any]:
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise ConfigErrors(
            [
                ConfigError(
                    code="YAML_ROOT_INVALID",
                    message="Top-level YAML document must be an object",
                    path=join_path(()),
                    location=str(source),
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
                    message=f"'{join_path(here)}' is defined in more than one file",
                    path=join_path(here),
                    location=str(source),
                    hint=f"Already set in {origin}" if origin else None,
                )
            )
    return merged


@dataclass(frozen=True)
class Manifest:
    """The ``api.yaml`` manifest for one spec, its ``templates:``/``include:`` globs resolved."""

    path: Path
    base_dir: Path

    @classmethod
    def discover(cls, spec_path: Path) -> Manifest:
        manifest_path = spec_path / _MANIFEST_FILENAME if spec_path.is_dir() else spec_path
        if spec_path.is_dir() and not manifest_path.is_file():
            raise ConfigErrors(
                [
                    ConfigError(
                        code="MANIFEST_NOT_FOUND",
                        message=f"No {_MANIFEST_FILENAME} found in spec directory",
                        path=join_path(()),
                        location=str(manifest_path),
                        hint=f"Create {manifest_path}",
                    )
                ]
            )
        return cls(manifest_path, manifest_path.parent)

    def load(self) -> dict[str, Any]:
        """Merge every ``templates:``/``include:`` match and the manifest's own body.

        Reads the manifest exactly once: its ``templates:``/``include:``
        values are peeked at the event level (no alias resolution), and its
        body -- which may itself alias a template anchor -- is loaded once,
        already seeded with the full template pool.
        """
        raw_templates, raw_include = _peek_globs(self.path)
        if raw_templates is None and raw_include is None:
            data, _ = load_file(self.path, AnchorPool.empty())
            return _ensure_dict(data, self.path)

        templates = self._validate_glob_list(raw_templates, "templates", "TEMPLATES_INVALID")
        include = self._validate_glob_list(raw_include, "include", "INCLUDE_INVALID")

        pool, template_errors = self._compose_templates(templates)
        if template_errors:
            raise ConfigErrors(template_errors)

        errors: list[ConfigError] = []
        provenance: dict[tuple[str, ...], Path] = {}
        merged: dict[str, Any] = {}
        for match in self._matches(include, code="INCLUDE_NO_MATCH", label="Include", errors=errors):
            try:
                fragment, _ = load_file(match, pool)
            except ConfigErrors as caught:
                errors.extend(caught.errors)
                continue
            merged = _deep_merge(merged, _ensure_dict(fragment, match), match, provenance, (), errors)

        try:
            overlay_root, _ = load_file(self.path, pool)
        except ConfigErrors as caught:
            errors.extend(caught.errors)
        else:
            overlay = {
                key: value
                for key, value in _ensure_dict(overlay_root, self.path).items()
                if key not in _MANIFEST_ONLY_KEYS
            }
            merged = _deep_merge(merged, overlay, self.path, provenance, (), errors)

        if errors:
            raise ConfigErrors(errors)
        return merged

    def _compose_templates(self, patterns: list[str]) -> tuple[AnchorPool, list[ConfigError]]:
        """Compose every ``templates:`` match, in glob order, into one pool.

        Only the anchors they define matter downstream, so each file's own
        data is discarded here.
        """
        errors: list[ConfigError] = []
        pool = AnchorPool.empty()
        for match in self._matches(patterns, code="TEMPLATES_NO_MATCH", label="Template", errors=errors):
            try:
                _, file_pool = load_file(match, pool)
            except ConfigErrors as caught:
                errors.extend(caught.errors)
                continue
            pool = pool.extend(file_pool)
        return pool, errors

    def _matches(self, patterns: list[str], *, code: str, label: str, errors: list[ConfigError]) -> list[Path]:
        """Resolve each pattern relative to the manifest, recording a no-match error per miss."""
        resolved: list[Path] = []
        for pattern in patterns:
            matches = sorted(self.base_dir.glob(pattern))
            if not matches:
                errors.append(
                    ConfigError(
                        code=code,
                        message=f"{label} pattern '{pattern}' matched no files",
                        path=join_path((pattern,)),
                        hint="Patterns are resolved relative to the manifest",
                    )
                )
                continue
            resolved.extend(matches)
        return resolved

    @staticmethod
    def _validate_glob_list(value: Any, key: str, code: str) -> list[str]:
        """Return ``value`` as a list of glob patterns, or fail fast on the wrong shape.

        Both ``include`` and ``templates`` use this, so the two manifest keys
        validate identically.
        """
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ConfigErrors(
                [ConfigError(code=code, message=f"'{key}' must be a list of glob patterns", path=join_path((key,)))]
            )
        return value
