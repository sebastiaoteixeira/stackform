"""Release values reach compose and systemd literally, whatever characters they hold."""

import pytest

from .support.deploy import deploy_bundle


@pytest.fixture(scope="module")
def filters(tmp_path_factory):
    return deploy_bundle(tmp_path_factory.mktemp("spec")).filters


@pytest.mark.parametrize(
    ("value", "quoted"),
    [
        ("plain", '"plain"'),
        ("pa$$word", '"pa\\$\\$word"'),
        ('say "hi"', '"say \\"hi\\""'),
        ("back\\slash", '"back\\\\slash"'),
        ("it's", '"it\'s"'),
        (8000, '"8000"'),
    ],
)
def test_env_file_values_are_double_quoted_literals(filters, value, quoted):
    assert filters["env_file_quote"](value) == quoted


@pytest.mark.parametrize("value", ["two\nlines", "carriage\rreturn"])
def test_multiline_values_are_rejected(filters, value):
    with pytest.raises(ValueError, match="one line"):
        filters["env_file_quote"](value)


def test_unit_values_escape_specifiers(filters):
    assert filters["unit_escape"]("date +%Y") == "date +%%Y"
    assert filters["unit_quote"]('GREETING=50% "off"') == '"GREETING=50%% \\"off\\""'
