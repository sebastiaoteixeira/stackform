"""Shared fixtures for unit tests exercising the YAML spec loader directly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class SpecTree:
    """A spec directory under construction, one file write at a time."""

    root: Path

    def write(self, relative_path: str, content: str) -> "SpecTree":
        """Write ``content`` to ``relative_path`` under the tree's root, and return self for chaining."""
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return self


@pytest.fixture
def spec_tree(tmp_path: Path) -> SpecTree:
    """An empty :class:`SpecTree` rooted at pytest's per-test ``tmp_path``."""
    return SpecTree(tmp_path)
