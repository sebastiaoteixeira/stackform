import pytest
from yaml_api_generator.runtime.claims import claim_value, resolve_claim_path


CLAIMS = {
    "realm_access": {"roles": ["admin", "user"]},
    "organization": {"acme": {"id": "org-123", "name": "Acme Corp"}},
    "sub": "user-42",
}


def test_plain_dotted_resolution() -> None:
    assert resolve_claim_path(CLAIMS, "sub") == "user-42"


def test_dotted_nested_resolution() -> None:
    assert resolve_claim_path(CLAIMS, "realm_access.roles") == ["admin", "user"]


def test_star_sole_entry() -> None:
    assert resolve_claim_path(CLAIMS, "organization.*.id") == "org-123"


def test_star_empty_dict_returns_none() -> None:
    assert resolve_claim_path({"organization": {}}, "organization.*.id") is None


def test_star_multiple_entries_returns_none() -> None:
    multi = {"organization": {"acme": {"id": "1"}, "beta": {"id": "2"}}}
    assert resolve_claim_path(multi, "organization.*.id") is None


def test_star_non_dict_returns_none() -> None:
    assert resolve_claim_path({"organization": "flat-string"}, "organization.*.id") is None


def test_missing_intermediate_key_returns_none() -> None:
    assert resolve_claim_path(CLAIMS, "realm_access.nonexistent") is None


def test_empty_path_returns_none() -> None:
    assert resolve_claim_path(CLAIMS, "") is None


def test_blank_path_returns_none() -> None:
    assert resolve_claim_path(CLAIMS, "   ") is None


def test_path_resolving_to_list_returns_list() -> None:
    result = resolve_claim_path(CLAIMS, "realm_access.roles")
    assert result == ["admin", "user"]


def test_exact_key_with_dots_wins_over_nested_walk() -> None:
    assert resolve_claim_path({"urn:oid:2.5.4.10": "ACME"}, "urn:oid:2.5.4.10") == "ACME"
    assert resolve_claim_path({"org.code": "flat", "org": {"code": "nested"}}, "org.code") == "flat"


@pytest.mark.parametrize(
    ("value", "field_type", "expected"),
    [
        ("ACME", "string", "ACME"),
        (7, "string", "7"),
        ("7", "number", 7.0),
        (7, "number", 7.0),
        ("seven", "number", None),
        ("true", "boolean", True),
        ("False", "boolean", False),
        ("no", "boolean", None),
        (["ACME", "BETA"], "string", None),
        ({"code": "ACME"}, "string", None),
        (None, "string", None),
    ],
)
def test_claim_value_converts_scalars_to_the_matched_field_type(value, field_type, expected) -> None:
    assert claim_value(value, field_type) == expected
