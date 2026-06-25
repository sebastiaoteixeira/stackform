"""Multi-file spec loading via include manifests."""

import pytest

from yaml_api_generator.parsers.yaml_parser import ConfigErrors, _load_spec


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_single_file_without_include_is_unchanged(tmp_path):
    spec = tmp_path / "spec.yaml"
    _write(spec, "version: '0.2'\nentities:\n  a: {fields: {id: {type: id}}}\n")

    assert _load_spec(spec) == {
        "version": "0.2",
        "entities": {"a": {"fields": {"id": {"type": "id"}}}},
    }


def test_directory_resolves_to_manifest(tmp_path):
    _write(tmp_path / "api.yaml", "version: '0.2'\ninclude: [parts/*.yaml]\n")
    _write(tmp_path / "parts" / "a.yaml", "entities:\n  a: {fields: {id: {type: id}}}\n")

    result = _load_spec(tmp_path)

    assert result == {
        "version": "0.2",
        "entities": {"a": {"fields": {"id": {"type": "id"}}}},
    }
    assert "include" not in result


def test_globs_deep_merge_shared_sections(tmp_path):
    _write(tmp_path / "api.yaml", "version: '0.2'\ninclude: [domains/*.yaml]\n")
    _write(tmp_path / "domains" / "a.yaml", "entities: {a: {}}\nservices: {a: {}}\n")
    _write(tmp_path / "domains" / "b.yaml", "entities: {b: {}}\nservices: {b: {}}\n")

    result = _load_spec(tmp_path)

    assert set(result["entities"]) == {"a", "b"}
    assert set(result["services"]) == {"a", "b"}


def test_duplicate_leaf_across_files_raises(tmp_path):
    _write(tmp_path / "api.yaml", "version: '0.2'\ninclude: [domains/*.yaml]\n")
    _write(tmp_path / "domains" / "a.yaml", "entities: {dup: {x: 1}}\n")
    _write(tmp_path / "domains" / "b.yaml", "entities: {dup: {x: 2}}\n")

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(tmp_path)
    assert any(e.code == "DUPLICATE_KEY" for e in exc.value.errors)


def test_include_pattern_with_no_match_raises(tmp_path):
    _write(tmp_path / "api.yaml", "version: '0.2'\ninclude: [missing/*.yaml]\n")

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(tmp_path)
    assert any(e.code == "INCLUDE_NO_MATCH" for e in exc.value.errors)


def test_missing_manifest_in_directory_raises(tmp_path):
    with pytest.raises(ConfigErrors) as exc:
        _load_spec(tmp_path)
    assert any(e.code == "MANIFEST_NOT_FOUND" for e in exc.value.errors)
