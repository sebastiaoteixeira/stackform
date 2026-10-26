"""Pagination: repository primitives, service mapping, controller strategy.

Covers the three layers the feature decomposes into -- repository primitives
applied backend-agnostically (offset and keyset over SQL and Mongo), the
implicit query-param -> primitive mapping, and the explicit controller grammar
with its build-time validation. offset and keyset are exercised end to end.
"""

import textwrap
from typing import Any

import pytest

from tests.unit.support.repositories import InMemoryRepository
from yaml_api_generator.ir import IRCollection
from yaml_api_generator.ir.api import IRPageSize, IRPagination, IRSortKey
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.server.common.pagination import (
    BoundKey,
    InvalidPageRequestError,
    Page,
    PageOverflowError,
    Primitives,
    SortKey,
    build_response,
    decode_position,
    encode_position,
    expand_bound,
    map_request,
)
from yaml_api_generator.server.common.repositories.mongodb import (
    MongoRepository,
    MongoRepositoryConfig,
    _mongo_bounds,
)
from yaml_api_generator.server.common.repositories.sql import SQLRepository
from yaml_api_generator.server.common.request_context import RequestContext
from yaml_api_generator.server.common.steps import RepositoryListStep


def _collection() -> IRCollection:
    return IRCollection(
        name="post",
        entity_name="post",
        type="base",
        idField="id",
        idFormat="natural",
        fields={
            "id": {"type": "id"},
            "score": {"type": "number"},
            "title": {"type": "string"},
        },
    )


_ROWS = [
    {"id": "a", "score": 10, "title": "a"},
    {"id": "b", "score": 10, "title": "b"},
    {"id": "c", "score": 20, "title": "c"},
    {"id": "d", "score": 5, "title": "d"},
    {"id": "e", "score": 20, "title": "e"},
]

_SCORE_ID_ORDER = ["d", "a", "b", "c", "e"]


@pytest.fixture
async def sql_repo():
    repo = SQLRepository("sqlite+aiosqlite://", [_collection()])
    repo.connect()
    for row in _ROWS:
        await repo.create("post", dict(row))
    yield repo
    await repo.close()


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [r["id"] for r in rows]


# --- repository primitives in isolation --------------------------------------


@pytest.mark.asyncio
async def test_omitting_all_primitives_is_unbounded(sql_repo):
    page = await sql_repo.paginate("post", Primitives())
    assert sorted(_ids(page.rows)) == ["a", "b", "c", "d", "e"]
    assert page.total is None


@pytest.mark.asyncio
async def test_limit_and_skip_primitives(sql_repo):
    sort = (SortKey("id", "asc"),)
    first = await sql_repo.paginate("post", Primitives(limit=2, sort=sort))
    assert _ids(first.rows) == ["a", "b"]
    second = await sql_repo.paginate("post", Primitives(limit=2, skip=2, sort=sort))
    assert _ids(second.rows) == ["c", "d"]


@pytest.mark.asyncio
async def test_sort_primitive_multi_field(sql_repo):
    sort = (SortKey("score", "asc"), SortKey("id", "asc"))
    page = await sql_repo.paginate("post", Primitives(sort=sort))
    assert _ids(page.rows) == _SCORE_ID_ORDER


@pytest.mark.asyncio
async def test_single_bound_range(sql_repo):
    bound = (BoundKey("score", "gte", 20),)
    page = await sql_repo.paginate("post", Primitives(bounds=(bound,)))
    assert sorted(_ids(page.rows)) == ["c", "e"]


@pytest.mark.asyncio
async def test_count_exact_reflects_scope_not_cursor(sql_repo):
    sort = (SortKey("score", "asc"), SortKey("id", "asc"))
    bound = (BoundKey("score", "gt", 10), BoundKey("id", "gt", "z"))
    page = await sql_repo.paginate(
        "post", Primitives(sort=sort, bounds=(bound,), count="exact")
    )
    assert page.total == 5


@pytest.mark.asyncio
async def test_base_repository_fallback_supports_custom_repositories():
    repository = InMemoryRepository({"post": _ROWS})
    primitives = Primitives(
        limit=2,
        skip=1,
        sort=(SortKey("score", "asc"), SortKey("id", "asc")),
        count="exact",
    )

    page = await repository.paginate("post", primitives)

    assert _ids(page.rows) == ["a", "b"]
    assert page.total == 5


# --- keyset lexicographic correctness (walk the whole set) -------------------


def _keyset_bound(cursor: dict[str, Any], sort):
    return tuple(
        BoundKey(key.field, "gt" if key.dir == "asc" else "lt", cursor[key.field])
        for key in sort
    )


async def _walk_keyset(repo, page_size, sort):
    seen: list[str] = []
    bounds: tuple = ()
    while True:
        page = await repo.paginate(
            "post", Primitives(limit=page_size, sort=sort, bounds=bounds)
        )
        if not page.rows:
            break
        seen.extend(_ids(page.rows))
        bounds = (_keyset_bound(page.rows[-1], sort),)
    return seen


@pytest.mark.asyncio
async def test_keyset_forward_paging_compound_sql(sql_repo):
    sort = (SortKey("score", "asc"), SortKey("id", "asc"))
    walked = await _walk_keyset(sql_repo, 2, sort)
    assert walked == _SCORE_ID_ORDER


@pytest.mark.asyncio
async def test_keyset_forward_paging_desc_tiebreaker_sql(sql_repo):
    sort = (SortKey("score", "desc"), SortKey("id", "asc"))
    walked = await _walk_keyset(sql_repo, 2, sort)
    assert walked == ["c", "e", "a", "b", "d"]


# --- Mongo backend: evaluate the compiled query in memory --------------------


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs

    def sort(self, spec):
        for field, direction in reversed(spec):
            self._docs.sort(key=lambda d: d[field], reverse=direction < 0)
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        return list(self._docs)


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    if "$and" in query:
        return all(_matches(doc, clause) for clause in query["$and"])
    if "$or" in query:
        return any(_matches(doc, clause) for clause in query["$or"])
    for field, condition in query.items():
        value = doc.get(field)
        if isinstance(condition, dict):
            for op, operand in condition.items():
                if op == "$gt" and not value > operand:
                    return False
                if op == "$gte" and not value >= operand:
                    return False
                if op == "$lt" and not value < operand:
                    return False
                if op == "$lte" and not value <= operand:
                    return False
        elif value != condition:
            return False
    return True


class FakeMongoCollection:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = [dict(d) for d in docs]

    def find(self, query):
        return FakeCursor([dict(d) for d in self._docs if _matches(d, query)])

    async def count_documents(self, query):
        return sum(1 for d in self._docs if _matches(d, query))


@pytest.fixture
def mongo_repo():
    repo = MongoRepository(MongoRepositoryConfig(uri="mongodb://x", database="db"))
    repo.register_id_field("post", "id")
    repo._db = {"post": FakeMongoCollection(_ROWS)}
    return repo


def test_mongo_bounds_compiles_lexicographic_or():
    bound = (BoundKey("score", "gt", 10), BoundKey("id", "gt", "b"))
    clauses = _mongo_bounds((bound,))
    assert clauses == [
        {"$or": [{"score": {"$gt": 10}}, {"score": 10, "id": {"$gt": "b"}}]}
    ]


@pytest.mark.asyncio
async def test_keyset_forward_paging_compound_mongo(mongo_repo):
    sort = (SortKey("score", "asc"), SortKey("id", "asc"))
    walked = await _walk_keyset(mongo_repo, 2, sort)
    assert walked == _SCORE_ID_ORDER


@pytest.mark.asyncio
async def test_mongo_count_exact_ignores_bounds(mongo_repo):
    sort = (SortKey("score", "asc"), SortKey("id", "asc"))
    bound = (BoundKey("score", "gt", 100), BoundKey("id", "gt", "z"))
    page = await mongo_repo.paginate(
        "post", Primitives(sort=sort, bounds=(bound,), count="exact")
    )
    assert page.rows == []
    assert page.total == 5


# --- bound expansion shape ---------------------------------------------------


def test_expand_bound_yields_prefixed_disjuncts():
    bound = (BoundKey("a", "gt", 1), BoundKey("b", "lt", 2), BoundKey("c", "gt", 3))
    disjuncts = list(expand_bound(bound))
    assert disjuncts[0] == ([], BoundKey("a", "gt", 1))
    assert disjuncts[1] == ([("a", 1)], BoundKey("b", "lt", 2))
    assert disjuncts[2] == ([("a", 1), ("b", 2)], BoundKey("c", "gt", 3))


# --- service mapping: query params -> primitives -----------------------------


def _offset(**kw) -> IRPagination:
    return IRPagination(strategy="offset", size=IRPageSize(default=2, max=5), **kw)


def _keyset(**kw) -> IRPagination:
    sort = (IRSortKey("score", "asc"), IRSortKey("id", "asc"))
    return IRPagination(
        strategy="keyset", size=IRPageSize(default=2, max=5), sort=sort, **kw
    )


def test_offset_mapping_defaults_and_clamp():
    default = map_request(_offset(), {})
    assert default.limit == 2 and default.skip == 0
    clamped = map_request(_offset(), {"limit": "99", "offset": "3"})
    assert clamped.limit == 5 and clamped.skip == 3


def test_offset_reject_over_max_raises():
    with pytest.raises(PageOverflowError):
        map_request(_offset(on_overflow="reject"), {"limit": "99"})


@pytest.mark.parametrize(
    ("pagination", "query", "parameter"),
    [
        (_offset(), {"limit": "invalid"}, "limit"),
        (_offset(), {"offset": "invalid"}, "offset"),
        (_offset(), {"limit": "-1"}, "limit"),
        (_offset(), {"offset": "-1"}, "offset"),
        (_offset(), {"limit": "0"}, "limit"),
        (_keyset(), {"limit": "0"}, "limit"),
    ],
)
def test_invalid_page_numbers_are_rejected(pagination, query, parameter):
    with pytest.raises(InvalidPageRequestError) as raised:
        map_request(pagination, query)
    assert raised.value.parameter == parameter


def test_keyset_mapping_fetches_one_extra_and_builds_bound():
    token = encode_position({"score": 10, "id": "b"}, (SortKey("score"), SortKey("id")))
    primitives = map_request(_keyset(), {"after": token, "limit": "2"})
    assert primitives.limit == 3
    assert primitives.bounds == (
        (BoundKey("score", "gt", 10), BoundKey("id", "gt", "b")),
    )


def test_keyset_position_token_round_trips():
    sort = (SortKey("score"), SortKey("id"))
    token = encode_position({"score": 20, "id": "c"}, sort)
    assert decode_position(token, sort) == [20, "c"]


# --- envelopes ---------------------------------------------------------------


def test_offset_envelope_off_is_bare_array():
    page = Page(rows=[{"id": "a"}], total=None)
    assert build_response(_offset(), page, {}) == [{"id": "a"}]


def test_offset_envelope_on_with_count():
    page = Page(rows=[{"id": "a"}], total=7)
    body = build_response(_offset(count="exact", envelope=True), page, {"offset": "4"})
    assert body == {"items": [{"id": "a"}], "limit": 2, "offset": 4, "total": 7}


def test_offset_envelope_on_count_none_omits_total():
    page = Page(rows=[], total=None)
    body = build_response(_offset(envelope=True), page, {})
    assert "total" not in body and body["items"] == []


def test_keyset_envelope_reports_hasmore_and_next():
    rows = [
        {"id": "d", "score": 5},
        {"id": "a", "score": 10},
        {"id": "b", "score": 10},
    ]
    body = build_response(_keyset(envelope=True), Page(rows=rows), {"limit": "2"})
    assert body["hasMore"] is True
    assert _ids(body["items"]) == ["d", "a"]
    assert decode_position(body["next"], (SortKey("score"), SortKey("id"))) == [10, "a"]


def test_keyset_envelope_last_page_has_no_next():
    rows = [{"id": "e", "score": 20}]
    body = build_response(_keyset(envelope=True), Page(rows=rows), {"limit": "2"})
    assert body["hasMore"] is False and body["next"] is None


# --- controller + service integration through RepositoryListStep -------------


def _ctx(repo, query):
    return RequestContext(
        method="GET", path="/posts", api_version=None, collection="post",
        operation="list", headers={}, url_params={}, repository=repo,
        principal=None, body=None, response=None, query=query,
    )


@pytest.mark.asyncio
async def test_list_step_without_pagination_is_bare_unbounded(sql_repo):
    step = RepositoryListStep("post", "id")
    ctx = await step(_ctx(sql_repo, None))
    assert isinstance(ctx.response, list) and len(ctx.response) == 5


@pytest.mark.asyncio
async def test_list_step_offset_envelope(sql_repo):
    step = RepositoryListStep("post", "id", _offset(count="exact", envelope=True))
    ctx = await step(_ctx(sql_repo, {"limit": ["2"], "offset": ["0"]}))
    assert ctx.response["total"] == 5
    assert ctx.response["limit"] == 2 and len(ctx.response["items"]) == 2


@pytest.mark.asyncio
async def test_list_step_keyset_pass_through_no_explicit_input(sql_repo):
    pagination = _keyset(envelope=True)
    step = RepositoryListStep("post", "id", pagination)
    first = await step(_ctx(sql_repo, {"limit": ["2"]}))
    assert _ids(first.response["items"]) == ["d", "a"]
    assert first.response["hasMore"] is True
    second = await step(_ctx(sql_repo, {"limit": ["2"], "after": [first.response["next"]]}))
    assert _ids(second.response["items"]) == ["b", "c"]


# --- controller grammar + build-time validation ------------------------------


_SPEC = """
version: "0.3"
api: { basePath: /api }
entities:
  post:
    fields:
      id: { type: id }
      score: { type: number, required: true }
      slug: { type: string, required: true, unique: true }
      title: { type: string }
repositories:
  posts: { entity: post }
services:
  posts: { repository: posts }
controllers:
  posts:
    service: posts
    base_path: /posts
    operations:
      list:
        pagination:
__PAGINATION__
"""


def _load(tmp_path, pagination: str):
    block = textwrap.indent(textwrap.dedent(pagination).strip(), "          ")
    spec = _SPEC.replace("__PAGINATION__", block)
    path = tmp_path / "spec.yaml"
    path.write_text(spec)
    return load_and_generate_ir(str(path)).ir


def _list_route(ir):
    return next(r for r in ir.routes if r.operation == "list")


def test_offset_pagination_parsed_onto_route(tmp_path):
    ir = _load(tmp_path, "strategy: offset\nsize: { default: 20, max: 100 }\ncount: exact\nenvelope: true")
    pagination = _list_route(ir).pagination
    assert pagination.strategy == "offset"
    assert pagination.size == IRPageSize(default=20, max=100)
    assert pagination.count == "exact" and pagination.envelope is True


def test_keyset_pagination_parsed_with_sort(tmp_path):
    ir = _load(
        tmp_path,
        "strategy: keyset\nsize: { default: 20, max: 100 }\nsort:\n  - { field: score, dir: desc }\n  - { field: id }",
    )
    pagination = _list_route(ir).pagination
    assert pagination.strategy == "keyset"
    assert pagination.sort == (IRSortKey("score", "desc"), IRSortKey("id", "asc"))


@pytest.mark.parametrize("unimplemented", ["strategy: cursor", "strategy: range", "strategy: offset\ncount: estimated"])
def test_unimplemented_modes_are_rejected_by_the_schema(tmp_path, unimplemented):
    with pytest.raises(ConfigErrors) as excinfo:
        _load(tmp_path, f"{unimplemented}\nsize: {{ default: 10, max: 50 }}")
    assert _error_codes(excinfo) == {"SCHEMA_VALIDATION_ERROR"}


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("[{ field: score, dir: desc }]", (IRSortKey("score", "desc"), IRSortKey("id", "asc"))),
        ("[{ field: score }, { field: slug }]", (IRSortKey("score", "asc"), IRSortKey("slug", "asc"))),
    ],
)
def test_offset_sort_ends_on_a_unique_field(tmp_path, sort, expected):
    ir = _load(tmp_path, f"strategy: offset\nsize: {{ default: 20, max: 100 }}\nsort: {sort}")
    assert _list_route(ir).pagination.sort == expected


def _error_codes(excinfo) -> set[str]:
    return {e.code for e in excinfo.value.errors}


def test_keyset_without_sort_is_coded_error(tmp_path):
    with pytest.raises(ConfigErrors) as excinfo:
        _load(tmp_path, "strategy: keyset\nsize: { default: 20, max: 100 }")
    assert "PAGINATION_KEYSET_SORT_REQUIRED" in _error_codes(excinfo)


def test_keyset_zero_default_is_schema_error(tmp_path):
    with pytest.raises(ConfigErrors) as excinfo:
        _load(
            tmp_path,
            "strategy: keyset\nsize: { default: 0, max: 100 }\nsort:\n  - { field: id }",
        )
    assert "SCHEMA_VALIDATION_ERROR" in _error_codes(excinfo)


def test_keyset_non_unique_tiebreaker_is_coded_error(tmp_path):
    with pytest.raises(ConfigErrors) as excinfo:
        _load(
            tmp_path,
            "strategy: keyset\nsize: { default: 20, max: 100 }\nsort:\n  - { field: score }",
        )
    assert "PAGINATION_KEYSET_TIEBREAKER_NOT_UNIQUE" in _error_codes(excinfo)


def test_keyset_unique_tiebreaker_is_accepted(tmp_path):
    ir = _load(
        tmp_path,
        "strategy: keyset\nsize: { default: 20, max: 100 }\nsort:\n  - { field: score }\n  - { field: slug }",
    )
    assert _list_route(ir).pagination.sort[-1] == IRSortKey("slug", "asc")


def test_keyset_nullable_sort_field_is_rejected(tmp_path):
    spec = _SPEC.replace(
        "score: { type: number, required: true }",
        "score: { type: number }",
    )
    block = textwrap.indent(
        "strategy: keyset\nsize: { default: 20, max: 100 }\nsort:\n  - { field: score }\n  - { field: id }",
        "          ",
    )
    path = tmp_path / "nullable.yaml"
    path.write_text(spec.replace("__PAGINATION__", block))

    with pytest.raises(ConfigErrors) as excinfo:
        load_and_generate_ir(str(path))
    assert "PAGINATION_KEYSET_SORT_FIELD_NULLABLE" in _error_codes(excinfo)


def test_unknown_sort_field_is_coded_error(tmp_path):
    with pytest.raises(ConfigErrors) as excinfo:
        _load(
            tmp_path,
            "strategy: keyset\nsize: { default: 20, max: 100 }\nsort:\n  - { field: nope }",
        )
    assert "PAGINATION_SORT_FIELD_UNKNOWN" in _error_codes(excinfo)


def test_size_default_over_max_is_coded_error(tmp_path):
    with pytest.raises(ConfigErrors) as excinfo:
        _load(tmp_path, "strategy: offset\nsize: { default: 100, max: 10 }")
    assert "PAGINATION_INVALID_SIZE" in _error_codes(excinfo)
