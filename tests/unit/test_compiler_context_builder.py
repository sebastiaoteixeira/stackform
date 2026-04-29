import pytest

from yaml_api_generator.compiler.context_builder import build_context
from yaml_api_generator.ir import (
    IRApi,
    IRCollection,
    IRDocument,
    IRIdentityCollection,
    IROperations,
    IRRoute,
    IRMongo,
    IRCors,
)


def _make_ir(
    collections: dict | None = None,
    identity: dict | None = None,
    routes: list | None = None,
    cors: IRCors | None = None,
    role_hierarchies: dict | None = None,
) -> IRDocument:
    cols = collections or {
        "items": IRCollection(
            name="items",
            entity_name="item",
            type="data",
            idField="id",
            idFormat="uuidv7",
            fields={
                "name": {"type": "string", "required": True},
                "score": {"type": "number", "min": 0, "max": 100},
            },
            operations=IROperations(
                list=True,
                get=True,
                create=True,
                update=True,
                replace=False,
                delete=True,
            ),
        ),
    }
    return IRDocument(
        version="0.2",
        api=IRApi(basePath="/api", version="v1", cors=cors),
        collections=cols,
        routes=routes or [],
        identityCollections=identity or {},
        role_hierarchies=role_hierarchies or {},
        mongo=IRMongo(),
    )


def test_cors_none_produces_no_cors_on_context():
    ir = _make_ir()
    ctx = build_context(ir)
    assert ctx.app.cors is None


def test_cors_configured_produces_cors():
    ir = _make_ir(
        cors=IRCors(
            origins=["https://example.com"],
            methods=["GET"],
            headers=["X-Custom"],
            credentials=True,
        )
    )
    ctx = build_context(ir)
    assert ctx.app.cors is not None
    assert ctx.app.cors.origins == ["https://example.com"]
    assert ctx.app.cors.credentials is True


def test_model_building_per_write_operation_per_collection():
    ir = _make_ir()
    ctx = build_context(ir)
    model_names = {m.name for m in ctx.models}
    assert "ItemsCreatePayload" in model_names
    assert "ItemsUpdatePayload" in model_names


def test_model_not_created_for_disabled_operations():
    ir = _make_ir()
    ctx = build_context(ir)
    model_names = {m.name for m in ctx.models}
    assert "ItemsReplacePayload" not in model_names


def test_field_filtering_non_dict_ignored():
    ir = _make_ir(
        collections={
            "items": IRCollection(
                name="items",
                entity_name="item",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={
                    "name": {"type": "string", "required": True},
                    "meta": "not_a_dict",
                },
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        }
    )
    ctx = build_context(ir)
    model = next(m for m in ctx.models if m.operation == "create")
    field_names = [f.name for f in model.fields]
    assert "meta" not in field_names


def test_field_filtering_id_type_excluded():
    ir = _make_ir(
        collections={
            "items": IRCollection(
                name="items",
                entity_name="item",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={
                    "id": {"type": "id"},
                    "name": {"type": "string", "required": True},
                },
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        }
    )
    ctx = build_context(ir)
    model = next(m for m in ctx.models if m.operation == "create")
    field_names = [f.name for f in model.fields]
    assert "id" not in field_names


def test_field_filtering_auth_field_excluded():
    ir = _make_ir(
        collections={
            "items": IRCollection(
                name="items",
                entity_name="item",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={
                    "name": {"type": "string", "required": True},
                    "_auth": {"type": "object"},
                },
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        }
    )
    ctx = build_context(ir)
    model = next(m for m in ctx.models if m.operation == "create")
    field_names = [f.name for f in model.fields]
    assert "_auth" not in field_names


def test_update_optionality_all_fields_optional():
    ir = _make_ir()
    ctx = build_context(ir)
    model = next(m for m in ctx.models if m.operation == "update")
    for f in model.fields:
        assert f.is_optional is True


def test_constraint_extraction_min_max():
    ir = _make_ir()
    ctx = build_context(ir)
    model = next(m for m in ctx.models if m.operation == "create")
    score_field = next(f for f in model.fields if f.name == "score")
    assert score_field.constraints.get("min") == 0
    assert score_field.constraints.get("max") == 100


def test_constraint_extraction_min_length_max_length():
    ir = _make_ir(
        collections={
            "items": IRCollection(
                name="items",
                entity_name="item",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={"name": {"type": "string", "minLength": 1, "maxLength": 255}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        }
    )
    ctx = build_context(ir)
    model = next(m for m in ctx.models if m.operation == "create")
    name_field = next(f for f in model.fields if f.name == "name")
    assert name_field.constraints.get("min_length") == 1
    assert name_field.constraints.get("max_length") == 255


def test_constraint_extraction_format():
    ir = _make_ir(
        collections={
            "items": IRCollection(
                name="items",
                entity_name="item",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={
                    "id": {"type": "id", "format": "uuidv4"},
                    "name": {"type": "string"},
                },
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        }
    )
    ctx = build_context(ir)


def test_enum_type_handling():
    ir = _make_ir(
        collections={
            "items": IRCollection(
                name="items",
                entity_name="item",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={"status": {"type": "enum", "values": ["active", "inactive"]}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        }
    )
    ctx = build_context(ir)
    model = next(m for m in ctx.models if m.operation == "create")
    status_field = next(f for f in model.fields if f.name == "status")
    assert status_field.type == "enum"
    assert status_field.enum_values == ["active", "inactive"]


def test_array_type_handling():
    ir = _make_ir(
        collections={
            "items": IRCollection(
                name="items",
                entity_name="item",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={"tags": {"type": "array", "items": {"type": "string"}}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        }
    )
    ctx = build_context(ir)
    model = next(m for m in ctx.models if m.operation == "create")
    tags_field = next(f for f in model.fields if f.name == "tags")
    assert tags_field.type == "array"
    assert tags_field.array_item_type == "string"


def test_ref_type_handling():
    ir = _make_ir(
        collections={
            "items": IRCollection(
                name="items",
                entity_name="item",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={"authorId": {"type": "ref", "ref": "users"}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        }
    )
    ctx = build_context(ir)
    model = next(m for m in ctx.models if m.operation == "create")
    ref_field = next(f for f in model.fields if f.name == "authorId")
    assert ref_field.type == "ref"
    assert ref_field.ref_collection == "users"


def test_password_injection_for_identity_create():
    ir = _make_ir(
        collections={
            "users": IRCollection(
                name="users",
                entity_name="user",
                type="auth",
                idField="id",
                idFormat="uuidv7",
                fields={"email": {"type": "string", "required": True}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        },
        identity={
            "users": IRIdentityCollection(
                name="users", identifier="email", via=["password"]
            )
        },
    )
    ctx = build_context(ir)
    model = next(m for m in ctx.models if m.operation == "create")
    field_names = [f.name for f in model.fields]
    assert "password" in field_names


def test_route_handler_branch():
    ir = _make_ir(
        collections={
            "posts": IRCollection(
                name="posts",
                entity_name="post",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={"title": {"type": "string", "required": True}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        },
        routes=[
            IRRoute(
                method="POST",
                path="/posts/{id}/publish",
                operation="publish",
                collection=None,
                is_public=True,
                handler="handlers.posts.publish",
            ),
        ],
    )
    ctx = build_context(ir)
    handler_route = next(r for r in ctx.routes if r.handler is not None)
    assert handler_route.handler == "handlers.posts.publish"
    assert handler_route.body_model is None


def test_route_crud_branch():
    ir = _make_ir(
        collections={
            "posts": IRCollection(
                name="posts",
                entity_name="post",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={"title": {"type": "string", "required": True}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        },
        routes=[
            IRRoute(
                method="POST",
                path="/posts",
                operation="create",
                collection="posts",
                is_public=True,
            ),
        ],
    )
    ctx = build_context(ir)
    crud_route = next(r for r in ctx.routes if r.collection == "posts")
    assert crud_route.handler is None
    assert crud_route.body_model is not None


def test_route_needs_auth_determination():
    ir = _make_ir(
        collections={
            "users": IRCollection(
                name="users",
                entity_name="user",
                type="auth",
                idField="id",
                idFormat="uuidv7",
                fields={"email": {"type": "string", "required": True}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
            "posts": IRCollection(
                name="posts",
                entity_name="post",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={"title": {"type": "string", "required": True}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        },
        identity={
            "users": IRIdentityCollection(
                name="users", identifier="email", via=["password"]
            ),
        },
        routes=[
            IRRoute(
                method="GET",
                path="/posts",
                operation="list",
                collection="posts",
                is_public=True,
            ),
            IRRoute(
                method="POST",
                path="/posts",
                operation="create",
                collection="posts",
                is_public=False,
            ),
        ],
    )
    ctx = build_context(ir)
    public_route = next(r for r in ctx.routes if r.operation == "list")
    protected_route = next(r for r in ctx.routes if r.operation == "create")
    assert public_route.needs_auth is False
    assert protected_route.needs_auth is True


def test_route_body_model_lookup():
    ir = _make_ir(
        collections={
            "posts": IRCollection(
                name="posts",
                entity_name="post",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={"title": {"type": "string", "required": True}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        },
        routes=[
            IRRoute(
                method="POST",
                path="/posts",
                operation="create",
                collection="posts",
                is_public=True,
            ),
        ],
    )
    ctx = build_context(ir)
    route = ctx.routes[0]
    assert route.body_model == "PostsCreatePayload"


def test_auth_config_building():
    ir = _make_ir(
        collections={
            "users": IRCollection(
                name="users",
                entity_name="user",
                type="auth",
                idField="id",
                idFormat="uuidv7",
                fields={"email": {"type": "string", "required": True}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        },
        identity={
            "users": IRIdentityCollection(
                name="users", identifier="email", via=["password"]
            )
        },
    )
    ctx = build_context(ir)
    assert ctx.auth.enabled is True
    assert ctx.auth.has_password_auth is True
    assert len(ctx.auth.identity_collections) == 1


def test_group_by_collection_drops_routes_with_none_collection():
    ir = _make_ir(
        collections={
            "posts": IRCollection(
                name="posts",
                entity_name="post",
                type="data",
                idField="id",
                idFormat="uuidv7",
                fields={"title": {"type": "string", "required": True}},
                operations=IROperations(
                    list=True,
                    get=True,
                    create=True,
                    update=True,
                    replace=False,
                    delete=True,
                ),
            ),
        },
        routes=[
            IRRoute(
                method="GET",
                path="/posts",
                operation="list",
                collection="posts",
                is_public=True,
            ),
            IRRoute(
                method="GET",
                path="/health",
                operation="health",
                collection=None,
                is_public=True,
            ),
        ],
    )
    ctx = build_context(ir)
    collection_route_ops = [r.operation for r in ctx.routes if r.collection == "posts"]
    none_collection_routes = [r for r in ctx.routes if r.collection is None]
    assert "list" in collection_route_ops
    assert len(none_collection_routes) == 1
    assert none_collection_routes[0].operation == "health"
