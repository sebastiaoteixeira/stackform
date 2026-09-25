"""Cross-file YAML anchor support via the `templates:` manifest key."""

import pytest

from yaml_api_generator.parsers.yaml_parser import ConfigErrors, _load_spec


def test_alias_whole_value_resolves_across_files(spec_tree):
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ntemplates: [templates/*.yaml]\ninclude: [domains/*.yaml]\n",
    )
    spec_tree.write("templates/fields.yaml", "_base: &idField {type: id}\n")
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      id: *idField\n",
    )

    result = _load_spec(spec_tree.root)

    assert result["entities"]["a"]["fields"]["id"] == {"type": "id"}


def test_merge_key_with_local_override_across_files(spec_tree):
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ntemplates: [templates/*.yaml]\ninclude: [domains/*.yaml]\n",
    )
    spec_tree.write(
        "templates/fields.yaml",
        "_base: &timestamps {createdAt: {type: datetime}, updatedAt: {type: datetime}}\n",
    )
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      <<: *timestamps\n      updatedAt: {type: string}\n",
    )

    result = _load_spec(spec_tree.root)

    assert result["entities"]["a"]["fields"] == {
        "createdAt": {"type": "datetime"},
        "updatedAt": {"type": "string"},
    }


def test_later_template_uses_earlier_template_anchor(spec_tree):
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ntemplates: [templates/*.yaml]\ninclude: [domains/*.yaml]\n",
    )
    spec_tree.write("templates/a-base.yaml", "_a: &idField {type: id}\n")
    spec_tree.write("templates/b-extra.yaml", "_b: {pk: *idField}\n")
    spec_tree.write(
        "domains/x.yaml",
        "entities:\n  x:\n    fields:\n      id: *idField\n",
    )

    result = _load_spec(spec_tree.root)

    assert result["entities"]["x"]["fields"]["id"] == {"type": "id"}


def test_template_data_is_not_merged_into_spec(spec_tree):
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ntemplates: [templates/*.yaml]\ninclude: [domains/*.yaml]\n",
    )
    spec_tree.write(
        "templates/fields.yaml",
        "entities:\n  ignored: {fields: {}}\n_base: &idField {type: id}\n",
    )
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      id: *idField\n",
    )

    result = _load_spec(spec_tree.root)

    assert set(result["entities"]) == {"a"}
    assert "templates" not in result
    assert "include" not in result


def test_unknown_alias_raises(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ninclude: [domains/*.yaml]\n")
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      id: *missing\n",
    )

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "TEMPLATE_UNKNOWN" for e in exc.value.errors)


def test_duplicate_anchor_across_template_files_raises(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ntemplates: [templates/*.yaml]\n")
    spec_tree.write("templates/a.yaml", "_a: &shared {type: id}\n")
    spec_tree.write("templates/b.yaml", "_b: &shared {type: string}\n")

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "TEMPLATE_DUPLICATE" for e in exc.value.errors)


def test_include_file_redefining_shared_anchor_raises(spec_tree):
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ntemplates: [templates/*.yaml]\ninclude: [domains/*.yaml]\n",
    )
    spec_tree.write("templates/fields.yaml", "_base: &idField {type: id}\n")
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      id: &idField {type: string}\n",
    )

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "TEMPLATE_DUPLICATE" for e in exc.value.errors)


def test_self_recursive_anchor_raises_cycle(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ninclude: [domains/*.yaml]\n")
    spec_tree.write("domains/a.yaml", "entities: &a [*a]\n")

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "TEMPLATE_CYCLE" for e in exc.value.errors)


def test_local_anchor_does_not_leak_to_sibling_include_file(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ninclude: [domains/*.yaml]\n")
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      id: &idField {type: id}\n",
    )
    spec_tree.write(
        "domains/b.yaml",
        "entities:\n  b:\n    fields:\n      id: *idField\n",
    )

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "TEMPLATE_UNKNOWN" for e in exc.value.errors)


def test_templates_pattern_with_no_match_raises(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ntemplates: [missing/*.yaml]\n")

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "TEMPLATES_NO_MATCH" for e in exc.value.errors)


def test_templates_invalid_type_raises(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ntemplates: not-a-list\n")

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "TEMPLATES_INVALID" for e in exc.value.errors)


def test_manifest_overlay_aliases_template_anchor(spec_tree):
    """The manifest's own body -- not just an `include` file -- can alias a template anchor.

    Regression test for the double-parse bug: the manifest used to be
    plain-parsed once (choking on this alias) before the template pool
    existed, and only re-parsed for includes.
    """
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ntemplates: [templates/*.yaml]\n"
        "entities:\n  a:\n    fields:\n      id: *idField\n",
    )
    spec_tree.write("templates/fields.yaml", "_base: &idField {type: id}\n")

    result = _load_spec(spec_tree.root)

    assert result["entities"]["a"]["fields"]["id"] == {"type": "id"}


def test_templates_without_include_merges_overlay_body(spec_tree):
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ntemplates: [templates/*.yaml]\n"
        "entities:\n  a:\n    fields:\n      id: *idField\n      name: {type: string}\n",
    )
    spec_tree.write("templates/fields.yaml", "_base: &idField {type: id}\n")

    result = _load_spec(spec_tree.root)

    assert result["entities"]["a"]["fields"] == {
        "id": {"type": "id"},
        "name": {"type": "string"},
    }
    assert "templates" not in result


def test_merge_key_with_sequence_of_aliases(spec_tree):
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ntemplates: [templates/*.yaml]\ninclude: [domains/*.yaml]\n",
    )
    spec_tree.write(
        "templates/fields.yaml",
        "_a: &timestamps {createdAt: {type: datetime}}\n_b: &flags {active: {type: boolean}}\n",
    )
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      <<: [*timestamps, *flags]\n      id: {type: id}\n",
    )

    result = _load_spec(spec_tree.root)

    assert result["entities"]["a"]["fields"] == {
        "createdAt": {"type": "datetime"},
        "active": {"type": "boolean"},
        "id": {"type": "id"},
    }


def test_template_merge_key_reused_by_two_includes(spec_tree):
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ntemplates: [templates/*.yaml]\ninclude: [domains/*.yaml]\n",
    )
    spec_tree.write(
        "templates/fields.yaml",
        "_timestamps: &timestamps {createdAt: {type: datetime}, updatedAt: {type: datetime}}\n",
    )
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      <<: *timestamps\n      id: {type: id}\n",
    )
    spec_tree.write(
        "domains/b.yaml",
        "entities:\n  b:\n    fields:\n      <<: *timestamps\n      id: {type: id}\n",
    )

    result = _load_spec(spec_tree.root)

    assert result["entities"]["a"]["fields"]["createdAt"] == {"type": "datetime"}
    assert result["entities"]["b"]["fields"]["createdAt"] == {"type": "datetime"}


def test_include_local_anchor_does_not_leak_into_overlay(spec_tree):
    """`api.yaml`'s own body is parsed against the template-only pool, never an include file's."""
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ninclude: [domains/*.yaml]\n"
        "entities:\n  b:\n    fields:\n      id: *idField\n",
    )
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      id: &idField {type: id}\n",
    )

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    assert any(e.code == "TEMPLATE_UNKNOWN" for e in exc.value.errors)


def test_unknown_alias_reports_location_and_close_match_hint(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ninclude: [domains/*.yaml]\n")
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      id: &idField {type: id}\n      pk: *idFeild\n",
    )

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    error = next(e for e in exc.value.errors if e.code == "TEMPLATE_UNKNOWN")
    assert error.location is not None
    assert str(spec_tree.root / "domains" / "a.yaml") in error.location
    assert error.hint == "Did you mean 'idField'?"


def test_duplicate_anchor_hint_names_origin_file(spec_tree):
    spec_tree.write("api.yaml", "version: '0.2'\ntemplates: [templates/*.yaml]\n")
    spec_tree.write("templates/a.yaml", "_a: &shared {type: id}\n")
    spec_tree.write("templates/b.yaml", "_b: &shared {type: string}\n")

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    error = next(e for e in exc.value.errors if e.code == "TEMPLATE_DUPLICATE")
    assert error.hint is not None
    assert str(spec_tree.root / "templates" / "a.yaml") in error.hint


def test_template_parse_error_does_not_cascade_to_includes(spec_tree):
    """A broken template file fails on its own -- it must not also spray TEMPLATE_UNKNOWN
    across every include file that would have aliased the anchor it never got to define."""
    spec_tree.write(
        "api.yaml",
        "version: '0.2'\ntemplates: [templates/*.yaml]\ninclude: [domains/*.yaml]\n",
    )
    spec_tree.write("templates/broken.yaml", "_a: [unterminated\n")
    spec_tree.write(
        "domains/a.yaml",
        "entities:\n  a:\n    fields:\n      id: *idField\n",
    )

    with pytest.raises(ConfigErrors) as exc:
        _load_spec(spec_tree.root)
    codes = {e.code for e in exc.value.errors}
    assert "YAML_PARSE_ERROR" in codes
    assert "TEMPLATE_UNKNOWN" not in codes
