import pytest

from yaml_api_generator.parsers.transformers.v02.binding_classifier import (
    classify_binding,
)


@pytest.mark.parametrize("value", ["public", "authenticated"])
@pytest.mark.parametrize("allow_where", [False, True])
def test_access_values_are_rejected_as_given_bindings(value, allow_where):
    binding, errors = classify_binding(
        value,
        "controllers.posts.routes.list.access[0].given.subject",
        {"user": "users"},
        allow_where=allow_where,
    )

    assert binding is None
    assert [error.code for error in errors] == ["ACCESS_RULE_INVALID"]
    assert errors[0].path.endswith("given.subject")
