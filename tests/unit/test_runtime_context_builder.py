from yaml_api_generator.runtime.runtime_context_builder import (
    build_runtime_context,
    _flatten_hierarchy,
)
from yaml_api_generator.ir import (
    IRApi,
    IRCollection,
    IRDocument,
    IRIdentityCollection,
    IROperations,
    IRRoute,
    IRMongo,
)


def _make_ir(
    collections: dict | None = None,
    identity: dict | None = None,
    role_hierarchies: dict | None = None,
    routes: list | None = None,
    cors=None,
) -> IRDocument:
    cols = collections or {
        "items": IRCollection(
            name="items",
            entity_name="item",
            type="data",
            idField="id",
            idFormat="uuidv7",
            fields={"name": {"type": "string", "required": True}},
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


def test_role_hierarchy_flattened_to_transitive_closure():
    hierarchy = {
        "admin": ["moderator"],
        "moderator": ["user"],
    }
    result = _flatten_hierarchy(hierarchy)
    assert result["admin"] == {"moderator", "user"}
    assert result["moderator"] == {"user"}


def test_has_password_auth_flag():
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
    ctx = build_runtime_context(ir)
    assert ctx.auth.has_password_auth is True
    assert ctx.auth.has_api_key_auth is False


def test_has_api_key_auth_flag():
    ir = _make_ir(
        collections={
            "clients": IRCollection(
                name="clients",
                entity_name="client",
                type="auth",
                idField="id",
                idFormat="uuidv7",
                fields={"clientId": {"type": "string", "required": True}},
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
            "clients": IRIdentityCollection(
                name="clients", identifier="clientId", via=["apiKey"]
            )
        },
    )
    ctx = build_runtime_context(ir)
    assert ctx.auth.has_api_key_auth is True
    assert ctx.auth.has_password_auth is False


def test_auth_enabled_only_when_identity_collections_exist():
    ir_no_auth = _make_ir()
    ctx = build_runtime_context(ir_no_auth)
    assert ctx.auth.enabled is False

    ir_with_auth = _make_ir(
        collections={
            "users": IRCollection(
                name="users",
                entity_name="user",
                type="auth",
                idField="id",
                idFormat="uuidv7",
                fields={"email": {"type": "string"}},
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
    ctx = build_runtime_context(ir_with_auth)
    assert ctx.auth.enabled is True


def test_collections_mapped_with_correct_descriptors():
    ir = _make_ir()
    ctx = build_runtime_context(ir)
    assert "items" in ctx.collections
    col = ctx.collections["items"]
    assert col.name == "items"
    assert col.id_field == "id"
    assert col.id_format == "uuidv7"


def test_routes_mapped_with_access_rules():
    from yaml_api_generator.ir import IRAccessRule, IRDocumentBinding

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
                method="DELETE",
                path="/posts/{id}",
                operation="delete",
                collection="posts",
                is_public=False,
                access_rules=[
                    IRAccessRule(
                        principal="identity:user",
                        required_role="admin",
                        document_symbols={"document": IRDocumentBinding(collection="posts", id_param="id")},
                        effect="allow",
                    ),
                ],
            ),
        ],
    )
    ctx = build_runtime_context(ir)
    assert len(ctx.routes) == 1
    route = ctx.routes[0]
    assert route.operation == "delete"
    assert route.access_rules is not None
    assert len(route.access_rules) == 1
    assert route.access_rules[0].principal == "identity:user"
    assert route.access_rules[0].required_role == "admin"
    assert route.access_rules[0].effect == "allow"
