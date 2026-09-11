import types
import uuid

import pytest
from bson import ObjectId

from yaml_api_generator.server.common.utils.value_compare import values_equal
from yaml_api_generator.server.common.when_eval import evaluate_when_with_symbols
from yaml_api_generator.ir.when import Equals, FieldRef
from yaml_api_generator.generators.backend.fastapi import access_filters
from yaml_api_generator.generators.backend.compile_context import (
    AccessRuleDescriptor,
    RequestSymbolDescriptor,
)


def _exec_values_equal():
    source = (
        "from typing import Any\n"
        "from uuid import UUID\n"
        "try:\n"
        "    from bson import ObjectId\n"
        "    _IDISH = (UUID, ObjectId)\n"
        "except ImportError:\n"
        "    _IDISH = (UUID,)\n"
        "def _values_equal(left: Any, right: Any) -> bool:\n"
        "    if left is None or right is None:\n"
        "        return left is None and right is None\n"
        "    if isinstance(left, bool) or isinstance(right, bool):\n"
        "        return isinstance(left, bool) and isinstance(right, bool) and left is right\n"
        "    if left == right:\n"
        "        return True\n"
        "    if isinstance(left, _IDISH) or isinstance(right, _IDISH):\n"
        "        return str(left) == str(right)\n"
        "    return False\n"
    )
    module = types.ModuleType("authorization_fragment")
    exec(compile(source, "<authz>", "exec"), module.__dict__)
    return module._values_equal


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


class TestEmittedValuesEqual:
    def test_emitted_values_equal_coerces_uuid_string(self):
        emitted = _exec_values_equal()
        u = uuid.uuid4()
        assert emitted(u, str(u)) is True

    def test_emitted_values_equal_unequal(self):
        emitted = _exec_values_equal()
        assert emitted(uuid.uuid4(), str(uuid.uuid4())) is False

    def test_emitted_values_equal_none(self):
        emitted = _exec_values_equal()
        assert emitted(None, "x") is False

    def test_emitted_values_equal_no_type_confusion(self):
        emitted = _exec_values_equal()
        assert emitted("1", 1) is False
        assert emitted("True", True) is False
        assert emitted(True, 1) is False
        assert emitted(True, True) is True


class TestRuleToPythonRegression:
    def test_target_body_field_equals_user_record_field_grants(self):
        rule = AccessRuleDescriptor(
            principal="user",
            required_role=None,
            when=Equals(
                left=FieldRef(root="target", path=("ownerId",)),
                right=FieldRef(root="user", path=("record", "id")),
            ),
            request_symbols=[
                RequestSymbolDescriptor(name="target", part=None, type_name="Membership")
            ],
            document_symbols=[],
        )
        binding = access_filters.request_symbol_binding(rule.request_symbols[0])
        assert binding == "target = _request_body"
        expr = access_filters.rule_to_python(rule)
        assert "_values_equal(" in expr
        assert 'target.get("ownerId")' in expr
        assert 'user.get("record", {}).get("id")' in expr

        oid = ObjectId()
        scope = {
            "target": {"ownerId": str(oid)},
            "user": {"record": {"id": oid}},
            "_values_equal": _exec_values_equal(),
        }
        assert eval(expr, scope) is True

        scope["user"] = {"record": {"id": ObjectId()}}
        assert eval(expr, scope) is False
