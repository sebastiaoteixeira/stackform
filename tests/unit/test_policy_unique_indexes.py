import json
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.fastapi import access_filters
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from yaml_api_generator.server.common.repositories.mongodb import (
    MongoRepository,
    MongoRepositoryConfig,
)
from yaml_api_generator.server.common.repositories.mongodb import _NON_NULL_BSON_TYPES
from yaml_api_generator.utils.strings import to_pascal_case, to_py_identifier
from tests.conftest import VALID_DIR

_BACKEND_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "yaml_api_generator" / "generators" / "backend"
)
_SHARED_DIR = _BACKEND_DIR / "shared" / "templates"
_FASTAPI_DIR = _BACKEND_DIR / "fastapi" / "templates"

_PARTIAL_FILTER_LEGAL_OPERATORS = frozenset(
    {"$eq", "$gt", "$gte", "$lt", "$lte", "$type", "$exists", "$and", "$or", "$in"}
)


class _RecordingCollection:
    def __init__(self, store):
        self.store = store

    async def create_index(self, field_name, **kwargs):
        self.store.append((field_name, kwargs))


class _RecordingDatabase:
    def __init__(self):
        self.calls = []

    def __getitem__(self, _name):
        return _RecordingCollection(self.calls)


def _render_mongodb_module():
    env = Environment(loader=FileSystemLoader(str(_SHARED_DIR)), keep_trailing_newline=True)
    return env.get_template("mongodb.py.jinja").render(settings_module="settings")


def _exec_initialize_indexes(source, database):
    module = types.ModuleType("mongodb_fragment")
    settings_module = types.ModuleType("settings")
    settings_module.settings = types.SimpleNamespace(
        MONGO_URI="mongodb://localhost", MONGO_DB="test"
    )
    with patch.dict(sys.modules, {"settings": settings_module}):
        exec(compile(source, "<mongodb>", "exec"), module.__dict__)
    module.__dict__["_db"] = database
    return module.initialize_indexes


def _render_app_module():
    env = Environment(
        loader=ChoiceLoader([FileSystemLoader(str(_FASTAPI_DIR)), FileSystemLoader(str(_SHARED_DIR))]),
        keep_trailing_newline=True,
    )
    env.filters["py_literal"] = access_filters.py_literal
    env.filters["py_identifier"] = to_py_identifier
    env.filters["py_bool"] = access_filters.py_bool
    env.filters["capitalize_collection"] = to_pascal_case
    ir = load_and_generate_ir(str(VALID_DIR / "auth-oidc-relations.yaml")).ir
    return env.get_template("app.py.jinja").render(ctx=build_context(ir))


def _collect_operators(node):
    operators = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.startswith("$"):
                operators.add(key)
            operators |= _collect_operators(value)
    elif isinstance(node, list):
        for item in node:
            operators |= _collect_operators(item)
    return operators


class TestUniqueIndexEmittedAtStartup:
    @pytest.mark.asyncio
    async def test_initialize_indexes_creates_unique_index_per_field(self):
        database = _RecordingDatabase()
        initialize_indexes = _exec_initialize_indexes(_render_mongodb_module(), database)
        await initialize_indexes({"users": ["email"], "organizations": ["keycloakOrgId"]})

        indexed = {field for field, _ in database.calls}
        assert indexed == {"email", "keycloakOrgId"}
        assert all(kwargs.get("unique") is True for _, kwargs in database.calls)

    def test_app_emits_unique_index_map_for_unique_fields(self):
        source = _render_app_module()
        match = re.search(r"initialize_mongo_indexes\((\{.*?\})\)", source)
        assert match is not None
        emitted = json.loads(match.group(1))
        assert emitted["users"] == ["email"]
        assert emitted["organizations"] == ["keycloakOrgId"]

    @pytest.mark.asyncio
    async def test_dev_create_unique_index_uses_unique_flag(self):
        calls = []
        repo = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
        repo._db = {"users": _RecordingCollection(calls)}
        await repo.create_unique_index("users", "email")
        field, kwargs = calls[0]
        assert field == "email"
        assert kwargs["unique"] is True


class _UpsertCollection:
    def __init__(self):
        self.docs = []

    async def find_one_and_update(self, match_filter, update, upsert, return_document):
        key, value = next(iter(match_filter.items()))
        existing = next((d for d in self.docs if d.get(key) == value), None)
        if existing is None:
            existing = {}
            existing.update(update.get("$setOnInsert", {}))
            self.docs.append(existing)
        existing.update(update.get("$set", {}))
        return dict(existing)


class TestPartialFilterValidity:
    async def _emitted_partial_filter(self):
        database = _RecordingDatabase()
        initialize_indexes = _exec_initialize_indexes(_render_mongodb_module(), database)
        await initialize_indexes({"users": ["email"]})
        return database.calls[0][1]["partialFilterExpression"]

    def test_emitted_partial_filter_has_no_ne(self):
        assert "$ne" not in _render_mongodb_module()

    def test_emitted_partial_filter_has_no_not(self):
        assert "$not" not in _render_mongodb_module()

    async def test_emitted_partial_filter_uses_only_legal_operators(self):
        operators = _collect_operators(await self._emitted_partial_filter())
        assert operators <= _PARTIAL_FILTER_LEGAL_OPERATORS
        assert operators, "partial filter must constrain the indexed field"

    async def test_dev_partial_filter_uses_only_legal_operators(self):
        calls = []
        repo = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
        repo._db = {"users": _RecordingCollection(calls)}
        await repo.create_unique_index("users", "email")
        operators = _collect_operators(calls[0][1]["partialFilterExpression"])
        assert "$ne" not in operators and "$not" not in operators
        assert operators <= _PARTIAL_FILTER_LEGAL_OPERATORS

    async def test_type_filter_excludes_null_and_missing(self):
        type_constraint = (await self._emitted_partial_filter())["email"]["$type"]
        assert "null" not in type_constraint
        assert type_constraint == _NON_NULL_BSON_TYPES


class TestAutoProvisionIdempotency:
    async def test_upsert_by_unique_key_is_idempotent(self):
        repo = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
        repo.register_id_field("users", "id")
        repo._db = {"users": _UpsertCollection()}

        first = await repo.upsert_by("users", "email", {"id": "u1", "email": "a@x.com", "name": "A"})
        second = await repo.upsert_by("users", "email", {"id": "u1", "email": "a@x.com", "name": "A2"})

        assert len(repo._db["users"].docs) == 1
        assert first["email"] == "a@x.com"
        assert second["name"] == "A2"
        assert second["id"] == "u1"

    async def test_upsert_by_null_key_raises(self):
        repo = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
        repo.register_id_field("users", "id")
        repo._db = {"users": _UpsertCollection()}

        with pytest.raises(ValueError, match="non-null value for key field 'email'"):
            await repo.upsert_by("users", "email", {"id": "u1", "name": "A"})
