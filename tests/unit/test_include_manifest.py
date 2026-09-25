"""Multi-file spec loading via include manifests."""

import pytest

from yaml_api_generator.parsers.yaml_parser import ConfigErrors, _load_spec


def test_single_file_without_include_is_unchanged(spec_tree):
    spec_tree.write("spec.yaml", "version: '0.2'\nentities:\n  a: {fields: {id: {type: id}}}\n")

    assert _load_spec(spec_tree.root / "spec.yaml") == {
        "version": "0.2",
        "entities": {"a": {"fields": {"id": {"type": "id"}}}},
    }


def test_directory_resolves_to_manifest(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ninclude: [parts/*.yaml]\n")
    spec_tree.write("parts/a.yaml", "entities:\n  a: {fields: {id: {type: id}}}\n")

    result = _load_spec(spec_tree.root)

    assert result == {
        "version": "0.2",
        "entities": {"a": {"fields": {"id": {"type": "id"}}}},
    }
    assert "include" not in result


def test_globs_deep_merge_shared_sections(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ninclude: [domains/*.yaml]\n")
    spec_tree.write("domains/a.yaml", "entities: {a: {}}\nservices: {a: {}}\n")
    spec_tree.write("domains/b.yaml", "entities: {b: {}}\nservices: {b: {}}\n")

    result = _load_spec(spec_tree.root)

    assert set(result["entities"]) == {"a", "b"}
    assert set(result["services"]) == {"a", "b"}


def test_duplicate_leaf_across_files_raises(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ninclude: [domains/*.yaml]\n")
    spec_tree.write("domains/a.yaml", "entities: {dup: {x: 1}}\n")
    spec_tree.write("domains/b.yaml", "entities: {dup: {x: 2}}\n")

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "DUPLICATE_KEY" for e in exc.value.errors)


def test_include_pattern_with_no_match_raises(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ninclude: [missing/*.yaml]\n")

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "INCLUDE_NO_MATCH" for e in exc.value.errors)


def test_missing_manifest_in_directory_raises(spec_tree):
    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "MANIFEST_NOT_FOUND" for e in exc.value.errors)


def test_include_invalid_type_raises(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ninclude: not-a-list\n")

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "INCLUDE_INVALID" for e in exc.value.errors)
