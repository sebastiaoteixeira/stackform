"""Tests for freely-named single-record path tokens (issue #57).

A v0.3 single-record op derives its fetch predicate from the route template
instead of assuming the ``{id}`` token: the final token identifies the record
by its id field and each preceding token scopes a same-named field. v0.2
``{id}`` routes keep the byte-identical id fetch and the exact
``Missing route parameter: id`` message.
"""

from typing import Any

import pytest

from tests.unit.support.repositories import InMemoryRepository
from yaml_api_generator.server.common.repositories import RepositoryRegistry
from yaml_api_generator.server.common.repositories.base import BaseRepository
from yaml_api_generator.server.common.request_context import RequestContext
from yaml_api_generator.server.common.server_context import (
    RuntimeAppConfig,
    RuntimeAuthConfig,
    RuntimeCollectionDescriptor,
    RuntimeContext,
    RuntimeRouteDescriptor,
)
from yaml_api_generator.server.common.steps import NotFoundError
from yaml_api_generator.server.common.steps.repositories import (
    RecordLocator,
    RepositoryDeleteStep,
    RepositoryGetStep,
    RepositoryReplaceStep,
    RepositoryUpdateStep,
    record_locator,
)
from yaml_api_generator.server.fastapi.factory import register_fastapi_routes


def _ctx(
    repo: BaseRepository,
    url_params: dict[str, str],
    *,
    collection: str = "c",
    operation: str = "get",
    body: dict[str, Any] | None = None,
) -> RequestContext:
    return RequestContext(
        method="GET",
        path="/",
        api_version="v1",
        collection=collection,
        operation=operation,
        headers={},
        url_params=url_params,
        repository=repo,
        principal=None,
        body=body,
        response=None,
    )


# --- token derivation -----------------------------------------------------


def test_record_locator_v02_id_token_unchanged():
    locator = record_locator("/api/v1/items/{id}", "id")
    assert locator == RecordLocator("id", "id", ())
    assert not locator.is_scoped
    assert locator.criteria({"id": "i1"}) == {"id": "i1"}


def test_record_locator_renamed_single_token_maps_to_id_field():
    locator = record_locator("/api/v1/categories/{categoryId}", "id")
    assert locator == RecordLocator("id", "categoryId", ())
    assert not locator.is_scoped
    assert locator.criteria({"categoryId": "c1"}) == {"id": "c1"}


def test_record_locator_multi_token_scopes_by_parents():
    locator = record_locator("/api/v1/orgs/{orgId}/members/{memberId}", "id")
    assert locator == RecordLocator("id", "memberId", (("orgId", "orgId"),))
    assert locator.is_scoped
    assert locator.criteria({"orgId": "o1", "memberId": "m1"}) == {"orgId": "o1", "id": "m1"}


def test_record_locator_honours_custom_id_field():
    locator = record_locator("/api/v1/countries/{code}", "code")
    assert locator == RecordLocator("code", "code", ())
    assert locator.criteria({"code": "PT"}) == {"code": "PT"}


# --- single-record steps: renamed token -----------------------------------


@pytest.mark.asyncio
async def test_get_step_renamed_token_fetches_record():
    repo = InMemoryRepository({"assetCategories": [{"id": "c1", "title": "Books"}]})
    repo.register_id_field("assetCategories", "id")
    step = RepositoryGetStep(
        "assetCategories", "id", record_locator("/api/v1/categories/{categoryId}", "id")
    )
    result = await step(_ctx(repo, {"categoryId": "c1"}, collection="assetCategories"))
    assert result.response["title"] == "Books"


@pytest.mark.asyncio
async def test_delete_step_renamed_token_removes_record():
    repo = InMemoryRepository({"assetCategories": [{"id": "c1", "title": "Books"}]})
    repo.register_id_field("assetCategories", "id")
    step = RepositoryDeleteStep(
        "assetCategories", "id", record_locator("/api/v1/categories/{categoryId}", "id")
    )
    result = await step(
        _ctx(repo, {"categoryId": "c1"}, collection="assetCategories", operation="delete")
    )
    assert result.response["id"] == "c1"
    assert repo.documents("assetCategories") == []


# --- single-record steps: multi-token nested path -------------------------


@pytest.mark.asyncio
async def test_get_step_multi_token_fetches_by_all_tokens():
    repo = InMemoryRepository(
        {"members": [
            {"id": "m1", "orgId": "o1", "name": "Ada"},
            {"id": "m1", "orgId": "o2", "name": "Wrong Org"},
        ]}
    )
    repo.register_id_field("members", "id")
    step = RepositoryGetStep(
        "members", "id", record_locator("/api/v1/orgs/{orgId}/members/{memberId}", "id")
    )
    result = await step(
        _ctx(repo, {"orgId": "o1", "memberId": "m1"}, collection="members")
    )
    assert result.response["name"] == "Ada"


@pytest.mark.asyncio
async def test_get_step_multi_token_wrong_parent_is_404():
    repo = InMemoryRepository({"members": [{"id": "m1", "orgId": "o1", "name": "Ada"}]})
    repo.register_id_field("members", "id")
    step = RepositoryGetStep(
        "members", "id", record_locator("/api/v1/orgs/{orgId}/members/{memberId}", "id")
    )
    with pytest.raises(NotFoundError):
        await step(_ctx(repo, {"orgId": "o2", "memberId": "m1"}, collection="members"))


@pytest.mark.asyncio
async def test_update_step_multi_token_scoped_mutates_matching_record():
    repo = InMemoryRepository({"members": [{"id": "m1", "orgId": "o1", "name": "old"}]})
    repo.register_id_field("members", "id")
    step = RepositoryUpdateStep(
        "members", "id", False, record_locator("/api/v1/orgs/{orgId}/members/{memberId}", "id")
    )
    result = await step(
        _ctx(
            repo,
            {"orgId": "o1", "memberId": "m1"},
            collection="members",
            operation="update",
            body={"name": "new"},
        )
    )
    assert result.response["name"] == "new"


@pytest.mark.asyncio
async def test_replace_step_multi_token_wrong_parent_is_404():
    repo = InMemoryRepository({"members": [{"id": "m1", "orgId": "o1", "name": "old"}]})
    repo.register_id_field("members", "id")
    step = RepositoryReplaceStep(
        "members", "id", False, record_locator("/api/v1/orgs/{orgId}/members/{memberId}", "id")
    )
    with pytest.raises(NotFoundError):
        await step(
            _ctx(
                repo,
                {"orgId": "o2", "memberId": "m1"},
                collection="members",
                operation="replace",
                body={"id": "m1", "orgId": "o2", "name": "x"},
            )
        )


# --- update / replace / delete resolve the record id across token styles --


@pytest.mark.asyncio
async def test_update_step_v02_id_token_mutates_record():
    repo = InMemoryRepository({"items": [{"id": "i1", "title": "old"}]})
    repo.register_id_field("items", "id")
    step = RepositoryUpdateStep("items", "id", False)
    result = await step(
        _ctx(repo, {"id": "i1"}, collection="items", operation="update", body={"title": "new"})
    )
    assert result.response["title"] == "new"


@pytest.mark.asyncio
async def test_update_step_renamed_token_mutates_record():
    repo = InMemoryRepository({"assetCategories": [{"id": "c1", "title": "old"}]})
    repo.register_id_field("assetCategories", "id")
    step = RepositoryUpdateStep(
        "assetCategories", "id", False, record_locator("/api/v1/categories/{categoryId}", "id")
    )
    result = await step(
        _ctx(
            repo,
            {"categoryId": "c1"},
            collection="assetCategories",
            operation="update",
            body={"title": "new"},
        )
    )
    assert result.response["title"] == "new"


@pytest.mark.asyncio
async def test_replace_step_v02_id_token_replaces_record():
    repo = InMemoryRepository({"items": [{"id": "i1", "title": "old", "extra": "drop"}]})
    repo.register_id_field("items", "id")
    step = RepositoryReplaceStep("items", "id", False)
    result = await step(
        _ctx(
            repo,
            {"id": "i1"},
            collection="items",
            operation="replace",
            body={"id": "i1", "title": "fresh"},
        )
    )
    assert result.response["title"] == "fresh"
    assert "extra" not in result.response


@pytest.mark.asyncio
async def test_replace_step_renamed_token_replaces_record():
    repo = InMemoryRepository(
        {"assetCategories": [{"id": "c1", "title": "old", "extra": "drop"}]}
    )
    repo.register_id_field("assetCategories", "id")
    step = RepositoryReplaceStep(
        "assetCategories", "id", False, record_locator("/api/v1/categories/{categoryId}", "id")
    )
    result = await step(
        _ctx(
            repo,
            {"categoryId": "c1"},
            collection="assetCategories",
            operation="replace",
            body={"id": "c1", "title": "fresh"},
        )
    )
    assert result.response["title"] == "fresh"
    assert "extra" not in result.response


@pytest.mark.asyncio
async def test_delete_step_v02_id_token_removes_record():
    repo = InMemoryRepository({"items": [{"id": "i1", "title": "gone"}]})
    repo.register_id_field("items", "id")
    step = RepositoryDeleteStep("items", "id")
    result = await step(_ctx(repo, {"id": "i1"}, collection="items", operation="delete"))
    assert result.response["id"] == "i1"
    assert repo.documents("items") == []


# --- per-token error message ----------------------------------------------


@pytest.mark.asyncio
async def test_missing_renamed_token_names_the_token():
    repo = InMemoryRepository({"assetCategories": []})
    repo.register_id_field("assetCategories", "id")
    step = RepositoryGetStep(
        "assetCategories", "id", record_locator("/api/v1/categories/{categoryId}", "id")
    )
    with pytest.raises(ValueError, match="^Missing route parameter: categoryId$"):
        await step(_ctx(repo, {}, collection="assetCategories"))


@pytest.mark.asyncio
async def test_missing_parent_token_names_the_token():
    repo = InMemoryRepository({"members": []})
    repo.register_id_field("members", "id")
    step = RepositoryGetStep(
        "members", "id", record_locator("/api/v1/orgs/{orgId}/members/{memberId}", "id")
    )
    with pytest.raises(ValueError, match="^Missing route parameter: orgId$"):
        await step(_ctx(repo, {"memberId": "m1"}, collection="members"))


# --- v0.2 regression ------------------------------------------------------


@pytest.mark.asyncio
async def test_v02_default_locator_preserves_missing_id_message():
    repo = InMemoryRepository({"items": []})
    repo.register_id_field("items", "id")
    step = RepositoryGetStep("items", "id")
    with pytest.raises(ValueError, match="^Missing route parameter: id$"):
        await step(_ctx(repo, {}, collection="items"))


@pytest.mark.asyncio
async def test_v02_default_locator_uses_id_fetch():
    repo = InMemoryRepository({"items": [{"id": "i1", "title": "kept"}]})
    repo.register_id_field("items", "id")
    step = RepositoryGetStep("items", "id")
    result = await step(_ctx(repo, {"id": "i1"}, collection="items"))
    assert result.response["title"] == "kept"


# --- end-to-end through the FastAPI factory / pipeline builder ------------


def _app(collections, routes, repo, *, spec_version="0.3"):
    from fastapi import FastAPI

    app = FastAPI()
    ctx = RuntimeContext(
        app=RuntimeAppConfig(base_path="/api", api_version="v1"),
        collections=collections,
        routes=routes,
        auth=RuntimeAuthConfig(
            enabled=False,
            identity_collections={},
            identity_id_fields={},
            has_password_auth=False,
            has_api_key_auth=False,
        ),
        spec_version=spec_version,
    )
    register_fastapi_routes(app, ctx, RepositoryRegistry.single(repo))
    return app


def _collection(name, id_field="id", fields=None):
    return RuntimeCollectionDescriptor(
        name=name,
        type="data",
        id_field=id_field,
        id_format="uuidv7",
        fields=fields or {},
    )


def test_fastapi_renamed_token_get_fetches():
    from fastapi.testclient import TestClient

    route = RuntimeRouteDescriptor(
        method="GET",
        path="/api/v1/categories/{categoryId}",
        operation="get",
        collection="assetCategories",
        is_public=True,
    )
    repo = InMemoryRepository({"assetCategories": [{"id": "c1", "title": "Books"}]})
    client = TestClient(
        _app({"assetCategories": _collection("assetCategories", fields={"title": {"type": "string"}})}, [route], repo)
    )
    resp = client.get("/api/v1/categories/c1")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Books"
    assert client.get("/api/v1/categories/missing").status_code == 404


def test_fastapi_multi_token_get_fetches_by_all_tokens():
    from fastapi.testclient import TestClient

    route = RuntimeRouteDescriptor(
        method="GET",
        path="/api/v1/orgs/{orgId}/members/{memberId}",
        operation="get",
        collection="members",
        is_public=True,
    )
    repo = InMemoryRepository({"members": [{"id": "m1", "orgId": "o1", "name": "Ada"}]})
    client = TestClient(
        _app(
            {"members": _collection("members", fields={"name": {"type": "string"}, "orgId": {"type": "string"}})},
            [route],
            repo,
        )
    )
    assert client.get("/api/v1/orgs/o1/members/m1").json()["name"] == "Ada"
    assert client.get("/api/v1/orgs/o2/members/m1").status_code == 404


def test_fastapi_v02_id_token_get_regression():
    from fastapi.testclient import TestClient

    route = RuntimeRouteDescriptor(
        method="GET",
        path="/api/v1/items/{id}",
        operation="get",
        collection="items",
        is_public=True,
    )
    repo = InMemoryRepository({"items": [{"id": "i1", "title": "kept"}]})
    client = TestClient(
        _app(
            {"items": _collection("items", fields={"title": {"type": "string"}})},
            [route],
            repo,
            spec_version="0.2",
        )
    )
    assert client.get("/api/v1/items/i1").json()["title"] == "kept"
    assert client.get("/api/v1/items/missing").status_code == 404


def test_fastapi_v02_renamed_token_does_not_enable_v03_lookup():
    from fastapi.testclient import TestClient

    route = RuntimeRouteDescriptor(
        method="GET",
        path="/api/v1/categories/{categoryId}",
        operation="get",
        collection="assetCategories",
        is_public=True,
    )
    repo = InMemoryRepository({"assetCategories": [{"id": "c1"}]})
    client = TestClient(
        _app(
            {"assetCategories": _collection("assetCategories")},
            [route],
            repo,
            spec_version="0.2",
        )
    )
    response = client.get("/api/v1/categories/c1")
    assert response.status_code == 422
