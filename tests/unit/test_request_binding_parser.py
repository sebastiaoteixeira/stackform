import pytest

from yaml_api_generator.ir import IRRequestBinding
from yaml_api_generator.parsers.when_parser import parse_request_binding
from yaml_api_generator.parsers.transformers.v02.access_transformer import (
    AccessTransformer,
)


_PATH = "test"


class TestParseRequestBinding:
    def test_whole_request_is_raw_with_no_part(self):
        result, errors = parse_request_binding("request", _PATH)
        assert not errors
        assert result == (None, None, True)

    def test_whole_request_typed_to_body(self):
        result, errors = parse_request_binding("request:createMembership", _PATH)
        assert not errors
        assert result == (None, "createMembership", False)

    @pytest.mark.parametrize(
        "part", ["body", "path", "query", "header", "cookie"]
    )
    def test_raw_part_binding(self, part):
        result, errors = parse_request_binding(f"request.{part}", _PATH)
        assert not errors
        assert result == (part, None, True)

    @pytest.mark.parametrize("part", ["body", "path", "query"])
    def test_typed_object_part_binding(self, part):
        result, errors = parse_request_binding(f"request.{part}:Membership", _PATH)
        assert not errors
        assert result == (part, "Membership", False)

    @pytest.mark.parametrize("part", ["header", "cookie"])
    def test_type_on_leaf_part_rejected(self, part):
        result, errors = parse_request_binding(f"request.{part}:Foo", _PATH)
        assert result is None
        assert errors[0].code == "REQUEST_TYPE_ON_LEAF"

    def test_unknown_part_rejected(self):
        result, errors = parse_request_binding("request.session", _PATH)
        assert result is None
        assert errors[0].code == "REQUEST_BINDING_INVALID"

    def test_part_qualified_leaf_in_given_rejected(self):
        result, errors = parse_request_binding("request.body.x", _PATH)
        assert result is None
        assert errors[0].code == "REQUEST_BINDING_INVALID"

    def test_empty_type_rejected(self):
        result, errors = parse_request_binding("request.body:", _PATH)
        assert result is None
        assert errors[0].code == "REQUEST_TYPE_NOT_FOUND"


class TestAccessTransformerRequestSymbols:
    def _parse(self, given: dict[str, str], when: str = "x.role equals 'admin'"):
        transformer = AccessTransformer()
        is_public, rules, errors = transformer.parse_access(
            [{"given": given, "when": when}],
            "test",
            auth_entities={"user"},
            entity_to_collection={"user": "users"},
        )
        return rules, errors

    def test_whole_request_binding(self):
        rules, errors = self._parse({"x": "request"})
        assert not errors
        assert rules[0].request_symbols["x"] == IRRequestBinding(
            part=None, type_name=None, raw=True
        )

    def test_typed_whole_request_binding(self):
        rules, errors = self._parse({"x": "request:createMembership"})
        assert not errors
        assert rules[0].request_symbols["x"] == IRRequestBinding(
            part=None, type_name="createMembership", raw=False
        )

    def test_raw_part_binding(self):
        rules, errors = self._parse({"x": "request.query"})
        assert not errors
        assert rules[0].request_symbols["x"] == IRRequestBinding(
            part="query", type_name=None, raw=True
        )

    def test_typed_part_binding(self):
        rules, errors = self._parse({"x": "request.body:createMembership"})
        assert not errors
        assert rules[0].request_symbols["x"] == IRRequestBinding(
            part="body", type_name="createMembership", raw=False
        )

    def test_arbitrary_symbol_name(self):
        rules, errors = self._parse(
            {"payload_data": "request.body"}, when="payload_data.role equals 'admin'"
        )
        assert not errors
        assert "payload_data" in rules[0].request_symbols

    def test_request_and_identity_coexist(self):
        rules, errors = self._parse(
            {"caller": "identity:user", "payload": "request:createMembership"},
            when="caller.role equals 'admin'",
        )
        assert not errors
        rule = rules[0]
        assert "caller" in rule.identity_symbols
        assert "payload" in rule.request_symbols
