import uuid

import pytest
from bson import ObjectId

from yaml_api_generator.server.common.utils.value_compare import values_equal
from yaml_api_generator.server.common.when_eval import evaluate_when_with_symbols
from yaml_api_generator.ir.when import Equals, FieldRef
from yaml_api_generator.generators.backend.fastapi import access_filters
from yaml_api_generator.runtime import access
from yaml_api_generator.runtime.access import EVERY_ROW, NO_ROW
from yaml_api_generator.generators.backend.compile_context import (
    AccessRuleDescriptor,
    RequestSymbolDescriptor,
)


class TestDevValuesEqual:
    def test_uuid_equals_its_string_form(self):
        u = uuid.uuid4()
        assert values_equal(u, str(u)) is True

    def test_objectid_equals_its_string_form(self):
        oid = ObjectId()
        assert values_equal(str(oid), oid) is True

    def test_unequal_uuid_string_is_unequal(self):
        assert values_equal(uuid.uuid4(), str(uuid.uuid4())) is False

    def test_none_never_coerces_to_string(self):
        assert values_equal(None, "None") is False

    def test_string_digit_does_not_match_int(self):
        assert values_equal("1", 1) is False

    def test_string_true_does_not_match_bool(self):
        assert values_equal("True", True) is False

    def test_bool_does_not_match_int(self):
        assert values_equal(True, 1) is False
        assert values_equal(1, True) is False

    def test_equal_bools_match(self):
        assert values_equal(True, True) is True

    def test_distinct_strings_do_not_match(self):
        assert values_equal("admin", "user") is False

    def test_both_none_match(self):
        assert values_equal(None, None) is True

    def test_when_eval_equals_uses_value_coercion(self):
        oid = ObjectId()
        expr = Equals(
            left=FieldRef(root="target", path=("ownerId",)),
            right=FieldRef(root="principal", path=("record", "id")),
        )
        symbols = {
            "target": {"ownerId": str(oid)},
            "principal": {"record": {"id": oid}},
        }
        assert evaluate_when_with_symbols(expr, symbols) is True

    def test_when_eval_equals_unequal_ids_denied(self):
        expr = Equals(
            left=FieldRef(root="target", path=("ownerId",)),
            right=FieldRef(root="principal", path=("record", "id")),
        )
        symbols = {
            "target": {"ownerId": str(ObjectId())},
            "principal": {"record": {"id": ObjectId()}},
        }
        assert evaluate_when_with_symbols(expr, symbols) is False


class TestRuleToPredicateRegression:
    def test_target_body_field_equals_user_record_field_grants(self):
        rule = AccessRuleDescriptor(
            principal="user",
            required_role=None,
            when=Equals(
                left=FieldRef(root="target", path=("ownerId",)),
                right=FieldRef(root="user", path=("record", "id")),
            ),
            request_symbols=[
                RequestSymbolDescriptor(name="target", part="body", type_name="Membership")
            ],
            document_symbols=[],
        )
        binding = access_filters.request_symbol_binding(rule.request_symbols[0])
        assert binding == "target = _request_body"
        expr = access_filters.rule_to_predicate(rule)

        oid = ObjectId()
        scope = {**vars(access), "target": {"ownerId": str(oid)}, "user": {"record": {"id": oid}}}
        assert eval(expr, scope) == EVERY_ROW

        scope["user"] = {"record": {"id": ObjectId()}}
        assert eval(expr, scope) == NO_ROW
