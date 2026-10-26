import pathlib

import pytest
from starlette.testclient import TestClient

from yaml_api_generator.ir import IRCors, IRPageSize, IRRolesConfig
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.server import build_app
from yaml_api_generator.server.common.loader import build_registry
from yaml_api_generator.server.common.repositories.mongodb import MongoRepository
from tests.conftest import INVALID_DIR, VALID_DIR
from tests.unit.support.generated_apps import write_spec

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples" / "valid"


# --- Test 125: Collection-based spec parsed correctly ---


def test_v01_blog_collections_parsed() -> None:
    result = load_and_generate_ir(str(EXAMPLES_DIR / "blog.yaml"))
    ir = result.ir
    assert "posts" in ir.collections
    assert "users" in ir.collections
    posts = ir.collections["posts"]
    assert "id" in posts.fields
    assert "title" in posts.fields
    assert "content" in posts.fields
    assert "tags" in posts.fields
    users = ir.collections["users"]
    assert "username" in users.fields
    posts_ops = {r.operation for r in ir.routes if r.collection == "posts"}
    assert "list" in posts_ops
    assert "replace" not in posts_ops
    users_ops = {r.operation for r in ir.routes if r.collection == "users"}
    assert "delete" in users_ops


def test_v01_mongo_block_is_the_default_datastore() -> None:
    ir = load_and_generate_ir(str(EXAMPLES_DIR / "blog.yaml")).ir
    assert ir.datastores == {ir.default_datastore: ir.mongo}
    assert isinstance(build_registry(ir).for_collection("posts"), MongoRepository)


# --- Test 126: ID field extraction edge cases ---


def test_v01_no_id_field_raises() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "v01-no-id-field.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "ID_FIELD_MISSING" in codes


def test_v01_multiple_id_fields_raises() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "v01-multiple-id-fields.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "ID_FIELD_MULTIPLE" in codes


# --- Test 127: Access policy per operation ---


def test_v01_access_policy_per_operation() -> None:
    result = load_and_generate_ir(str(EXAMPLES_DIR / "auth-users.yaml"))
    ir = result.ir
    users_routes = [r for r in ir.routes if r.collection == "users"]
    create_route = next(r for r in users_routes if r.operation == "create")
    assert create_route.is_public is True
    list_route = next(r for r in users_routes if r.operation == "list")
    assert list_route.is_public is False
    get_route = next(r for r in users_routes if r.operation == "get")
    assert get_route.is_public is False
    posts_routes = [r for r in ir.routes if r.collection == "posts"]
    posts_create = next(r for r in posts_routes if r.operation == "create")
    assert posts_create.is_public is True
    posts_update = next(r for r in posts_routes if r.operation == "update")
    assert posts_update.is_public is False


# --- Test 128: Default public if no access specified ---


def test_v01_default_public_when_no_access() -> None:
    result = load_and_generate_ir(str(VALID_DIR / "v01-no-access-defaults.yaml"))
    ir = result.ir
    for route in ir.routes:
        assert route.is_public is True


# --- Test 129: Login route auto-generated for password auth ---


def test_v01_login_route_auto_generated_for_password() -> None:
    result = load_and_generate_ir(str(EXAMPLES_DIR / "auth-users.yaml"))
    ir = result.ir
    login_routes = [r for r in ir.routes if r.operation == "login"]
    assert len(login_routes) == 1
    assert login_routes[0].method == "POST"
    assert login_routes[0].path == "/api/v1/users/login"
    assert login_routes[0].is_public is True


# --- Test 130: No login route for apiKey-only auth ---


def test_v01_no_login_route_for_api_key_only() -> None:
    result = load_and_generate_ir(str(EXAMPLES_DIR / "auth-api-key.yaml"))
    ir = result.ir
    login_routes = [r for r in ir.routes if r.operation == "login"]
    assert len(login_routes) == 0


# --- Test 131: "authenticated" keyword → not public ---


def test_v01_authenticated_keyword_not_public() -> None:
    result = load_and_generate_ir(str(EXAMPLES_DIR / "auth-users.yaml"))
    ir = result.ir
    users_routes = [r for r in ir.routes if r.collection == "users"]
    list_route = next(r for r in users_routes if r.operation == "list")
    assert list_route.is_public is False
    update_route = next(r for r in users_routes if r.operation == "update")
    assert update_route.is_public is False


# --- Test 132: Identity-based access in v0.1 format ---


def test_v01_identity_based_access() -> None:
    result = load_and_generate_ir(str(EXAMPLES_DIR / "auth-users.yaml"))
    ir = result.ir
    users_routes = [r for r in ir.routes if r.collection == "users"]
    delete_route = next(r for r in users_routes if r.operation == "delete")
    assert delete_route.is_public is False


# --- Test 133: Auth field validation (password/passwordHash forbidden) ---


def test_v01_password_field_forbidden() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "v01-password-field-forbidden.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "AUTH_PASSWORD_FIELD_FORBIDDEN" in codes


def test_v01_password_hash_field_forbidden() -> None:
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(INVALID_DIR / "v01-password-field-forbidden.yaml"))
    codes = {e.code for e in exc_info.value.errors}
    assert "AUTH_PASSWORD_HASH_FIELD_FORBIDDEN" in codes


_PLATFORM_SPEC = """
version: "0.1"
{top}
collections:
  users:
    type: auth
    auth: {{ identifier: email, via: password }}
    {roles}
    fields:
      id: {{ type: id }}
      email: {{ type: string, required: true, unique: true }}
  posts:
    fields:
      id: {{ type: id }}
      {field}: {{ type: string, minLength: {min_length}, maxLength: 5 }}
"""


def _platform_ir(tmp_path, top="", roles="", field="title", min_length=1):
    spec = write_spec(tmp_path, _PLATFORM_SPEC.format(top=top, roles=roles, field=field, min_length=min_length))
    return load_and_generate_ir(str(spec)).ir


def _platform_errors(tmp_path, **parts) -> list[tuple[str, str]]:
    with pytest.raises(ConfigErrors) as exc_info:
        _platform_ir(tmp_path, **parts)
    return [(e.code, e.path) for e in exc_info.value.errors]


def _list_page_size(ir) -> IRPageSize:
    return next(r.pagination.size for r in ir.routes if r.collection == "posts" and r.operation == "list")


@pytest.mark.parametrize(
    ("pagination", "size"),
    [
        ("", IRPageSize(default=20, max=100)),
        ("api: { pagination: { defaultPageSize: 5, maxPageSize: 50 } }", IRPageSize(default=5, max=50)),
        ("api: { pagination: { maxPageSize: 10 } }", IRPageSize(default=10, max=10)),
    ],
    ids=["defaults", "explicit", "max-below-default"],
)
def test_v01_pagination_sizes_list_routes(tmp_path, pagination, size) -> None:
    assert _list_page_size(_platform_ir(tmp_path, top=pagination)) == size


def test_v01_security_block_reaches_api_ir(tmp_path) -> None:
    security = (
        "security:\n"
        "  cors: { allowedOrigins: [\"https://app.example\"], allowedMethods: [GET], allowCredentials: true }\n"
        "  headers: { enableStandard: false }"
    )
    api = _platform_ir(tmp_path, top=security).api
    assert (api.cors, api.security_headers) == (
        IRCors(origins=["https://app.example"], methods=["GET"], credentials=True),
        False,
    )


def test_v01_roles_parsed_into_identity_collection(tmp_path) -> None:
    roles = "roles: { values: [reader, editor], default: reader, hierarchy: { editor: [reader] } }"
    assert _platform_ir(tmp_path, roles=roles).identityCollections["users"].roles == IRRolesConfig(
        values=("reader", "editor"), default="reader", hierarchy={"editor": ("reader",)}
    )


def test_v01_roles_hierarchy_unknown_role_rejected(tmp_path) -> None:
    roles = "roles: { values: [reader], default: reader, hierarchy: { admin: [reader] } }"
    assert _platform_errors(tmp_path, roles=roles) == [
        ("ROLES_HIERARCHY_UNKNOWN_ROLE", "collections.users.roles.hierarchy")
    ]


def test_v01_roles_default_must_be_declared(tmp_path) -> None:
    roles = "roles: { values: [reader, editor], default: admin }"
    assert _platform_errors(tmp_path, roles=roles) == [("ROLES_DEFAULT_UNKNOWN_ROLE", "collections.users.roles.default")]


def test_v01_shared_validators_check_collections(tmp_path) -> None:
    assert _platform_errors(tmp_path, field="class") == [("INVALID_FIELD_NAME", "collections.posts.fields.class")]
    assert [code for code, _ in _platform_errors(tmp_path, min_length=9)] == ["FIELD_CONSTRAINT_INVALID"]


def test_v01_example_serves_on_dev_server() -> None:
    client = TestClient(build_app(str(EXAMPLES_DIR / "blog.yaml")))
    assert "/api/posts" in client.get("/openapi.json").json()["paths"]
