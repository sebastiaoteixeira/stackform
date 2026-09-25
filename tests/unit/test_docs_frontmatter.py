from pathlib import Path

import pytest
import yaml

DOCS_ROOT = Path(__file__).resolve().parents[2] / "docs"

FRONTMATTER_DELIMITER = "---\n"


def _pages() -> list[Path]:
    return sorted(DOCS_ROOT.rglob("*.md"))


def _frontmatter(page: Path) -> dict:
    text = page.read_text(encoding="utf-8")
    assert text.startswith(FRONTMATTER_DELIMITER), (
        f"{page.relative_to(DOCS_ROOT)} has no frontmatter block; "
        "the docs site renders its filename as the page title"
    )
    _, block, _ = text.split(FRONTMATTER_DELIMITER, 2)
    return yaml.safe_load(block)


@pytest.mark.parametrize("page", _pages(), ids=lambda page: str(page.relative_to(DOCS_ROOT)))
def test_page_declares_title_and_description(page: Path) -> None:
    metadata = _frontmatter(page)
    assert isinstance(metadata, dict), f"{page.relative_to(DOCS_ROOT)} frontmatter is not a mapping"
    assert metadata.get("title"), f"{page.relative_to(DOCS_ROOT)} declares no title"
    assert metadata.get("description"), f"{page.relative_to(DOCS_ROOT)} declares no description"


@pytest.mark.parametrize(
    "version_root",
    sorted(path for path in DOCS_ROOT.glob("v*") if path.is_dir()),
    ids=lambda path: path.name,
)
def test_version_folder_has_landing_page(version_root: Path) -> None:
    assert (version_root / "index.md").is_file(), (
        f"docs/{version_root.name} has no index.md, so /docs/{version_root.name} is a 404"
    )
