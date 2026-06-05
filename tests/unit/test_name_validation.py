import pytest

from yaml_api_generator.parsers.transformers.name_validation import (
    validate_spec_names,
)


def _codes(entities: dict) -> set[str]:
    return {error.code for error in validate_spec_names({"entities": entities})}


def _entity() -> dict:
    return {"fields": {"id": {"type": "id"}}}


# ---- NAME_PASCAL_CASE_COLLISION ----

@pytest.mark.parametrize(
    "names",
    [
        ("userProfile", "user_profile"),
        ("user-profile", "userProfile"),
        ("apiKey", "api_key"),
    ],
)
def test_distinct_names_colliding_to_same_pascal_case_rejected(names):
    entities = {name: _entity() for name in names}
    assert "NAME_PASCAL_CASE_COLLISION" in _codes(entities)


def test_distinct_pascal_case_names_accepted():
    entities = {"userProfile": _entity(), "userAccount": _entity()}
    assert "NAME_PASCAL_CASE_COLLISION" not in _codes(entities)


def test_single_entity_no_collision():
    assert "NAME_PASCAL_CASE_COLLISION" not in _codes({"userProfile": _entity()})


# ---- existing identifier validation still applies ----

def test_keyword_entity_name_rejected():
    assert "INVALID_NAME" in _codes({"class": _entity()})
