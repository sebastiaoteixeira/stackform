from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.generators.backend.fastapi.type_mapper import PayloadModule
from yaml_api_generator.generators.backend.compile_context import (
    AppConfig,
    AuthConfig,
    CompileContext,
    FieldDescriptor,
    ModelDescriptor,
)
from yaml_api_generator.generators.backend.builders.settings_builder import build_settings_fields
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.ir.api import IROIDCProvider, IRSAMLProvider
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from tests.conftest import VALID_DIR


def _ctx_from_fixture(fixture_name: str):
    result = load_and_generate_ir(str(VALID_DIR / fixture_name))
    return build_context(result.ir)


def test_fastapi_output_directory_structure_created(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "app.py").exists()
    assert (tmp_path / "models").is_dir()
    assert (tmp_path / "routes").is_dir()
    assert (tmp_path / "services").is_dir()
    assert (tmp_path / "repositories").is_dir()
    assert (tmp_path / "dependencies").is_dir()
    assert (tmp_path / "dependencies" / "repositories.py").exists()
    assert (tmp_path / "dependencies" / "services.py").exists()
    assert (tmp_path / "requirements.txt").exists()


def test_fastapi_models_file_per_collection_with_write_ops(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "models" / "posts.py").exists()


def test_fastapi_routes_file_per_collection_with_routes(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "routes" / "posts.py").exists()


def test_fastapi_login_routes_only_when_password_auth(tmp_path):
    ctx = _ctx_from_fixture("auth-password.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "routes" / "login.py").exists()

    ctx_no_auth = _ctx_from_fixture("basic-crud.yaml")
    gen2 = FastAPIGenerator()
    out2 = tmp_path / "noauth"
    gen2.generate(ctx_no_auth, out2)
    assert not (out2 / "routes" / "login.py").exists()


def test_fastapi_auth_dependencies_only_when_auth_enabled(tmp_path):
    ctx = _ctx_from_fixture("auth-password.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "dependencies" / "auth.py").exists()

    ctx_no_auth = _ctx_from_fixture("basic-crud.yaml")
    gen2 = FastAPIGenerator()
    out2 = tmp_path / "noauth2"
    gen2.generate(ctx_no_auth, out2)
    assert not (out2 / "dependencies" / "auth.py").exists()


def test_fastapi_jwt_utils_only_when_password_auth(tmp_path):
    ctx = _ctx_from_fixture("auth-password.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "dependencies" / "jwt_utils.py").exists()

    ctx_no_auth = _ctx_from_fixture("basic-crud.yaml")
    gen2 = FastAPIGenerator()
    out2 = tmp_path / "noauth3"
    gen2.generate(ctx_no_auth, out2)
    assert not (out2 / "dependencies" / "jwt_utils.py").exists()


def test_fastapi_cors_middleware_when_configured(tmp_path):
    from yaml_api_generator.ir import IRCors

    result = load_and_generate_ir(str(VALID_DIR / "basic-crud.yaml"))
    ir = result.ir
    ir_with_cors = ir.__class__(
        version=ir.version,
        api=ir.api.__class__(
            basePath=ir.api.basePath,
            version=ir.api.version,
            cors=IRCors(origins=["*"], methods=["*"], headers=["*"], credentials=True),
        ),
        collections=ir.collections,
        routes=ir.routes,
        identityCollections=ir.identityCollections,
        mongo=ir.mongo,
    )
    ctx = build_context(ir_with_cors)
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    app_content = (tmp_path / "app.py").read_text()
    assert "CORSMiddleware" in app_content


def test_fastapi_payload_module_maps_every_field_type():
    fields = {
        "s": {"type": "string", "required": True},
        "n": {"type": "number", "required": True},
        "b": {"type": "boolean", "required": True},
        "d": {"type": "datetime", "required": True},
        "e": {"type": "enum", "values": ["a", "b"], "required": True},
        "a": {"type": "array", "items": {"type": "string"}, "required": True},
        "o": {"type": "object", "required": True},
        "r": {"type": "ref", "ref": "users", "required": True},
    }
    model = ModelDescriptor(
        "ItemsFields", "items", "fields", [FieldDescriptor(n, c) for n, c in fields.items()]
    )
    (declaration,) = PayloadModule([model]).declarations
    assert {a.name: a.annotation for a in declaration.attributes} == {
        "s": "str",
        "n": "Annotated[float, Field(strict=True)]",
        "b": "Annotated[bool, Field(strict=True)]",
        "d": "Timestamp",
        "e": "Literal['a', 'b']",
        "a": "list[str]",
        "o": "dict[str, Any]",
        "r": "str",
    }


def test_drf_project_scaffold(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = DRFGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "manage.py").exists()
    assert (tmp_path / "project" / "settings.py").exists()
    assert (tmp_path / "project" / "urls.py").exists()
    assert (tmp_path / "project" / "asgi.py").exists()
    assert (tmp_path / "project" / "wsgi.py").exists()


def test_drf_registers_the_login_route_it_emits(tmp_path):
    ctx = _ctx_from_fixture("request-access.yaml")
    gen = DRFGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "api" / "views" / "login.py").exists()
    assert "LoginView" in (tmp_path / "api" / "urls.py").read_text()


def test_drf_serializers_per_collection(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = DRFGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "api" / "serializers" / "posts.py").exists()


def test_drf_views_per_collection(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = DRFGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "api" / "views" / "posts.py").exists()
    content = (tmp_path / "api" / "views" / "posts.py").read_text()
    assert "class PostsView(APIView)" in content
    assert "class PostsByIdView(APIView)" in content


def test_drf_access_rule_enforcement_in_views(tmp_path):
    ctx = _ctx_from_fixture("roles-access.yaml")
    gen = DRFGenerator()
    gen.generate(ctx, tmp_path)
    views_dir = tmp_path / "api" / "views"
    assert views_dir.exists()
    posts_view = (views_dir / "posts.py").read_text()
    assert len(posts_view) > 0


def test_drf_serializers_declare_payload_properties(tmp_path):
    DRFGenerator().generate(_ctx_from_fixture("basic-crud.yaml"), tmp_path)
    serializers = next((tmp_path / "api" / "serializers").glob("[!_]*.py")).read_text()
    assert "(PayloadSerializer):" in serializers
    assert "properties = {" in serializers


def test_raw_asgi_app_file(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = RawASGIGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "app.py").exists()
    content = (tmp_path / "app.py").read_text()
    assert "ROUTES" in content or "ASGIApp" in content


def test_raw_path_to_regex_conversion():
    import re
    from yaml_api_generator.generators.backend.raw.generator import _path_to_regex

    pattern = re.compile(_path_to_regex("/posts/{id}"))
    assert pattern.match("/posts/abc123") is not None
    assert pattern.match("/posts/abc123").group("id") == "abc123"
    assert pattern.match("/other/abc123") is None


def test_raw_validation_file(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = RawASGIGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "validation.py").exists()


def test_raw_reuses_fastapi_templates(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = RawASGIGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "services" / "exceptions.py").exists()
    assert (tmp_path / "repositories" / "posts.py").exists()
    assert (tmp_path / "dependencies" / "mongodb.py").exists()


def test_fastapi_jwt_utils_generated_for_oidc_without_password(tmp_path):
    ctx = _ctx_from_fixture("auth-oidc.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    assert not ctx.auth.has_password_auth
    assert ctx.auth.has_oidc_auth
    assert (tmp_path / "dependencies" / "jwt_utils.py").exists()
    auth_src = (tmp_path / "dependencies" / "auth.py").read_text()
    assert "from dependencies.jwt_utils import decode_jwt_token" in auth_src


def test_generated_settings_uses_secretstr_for_secrets(tmp_path):
    ctx = _ctx_from_fixture("auth-oidc.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    settings_src = (tmp_path / "settings.py").read_text()
    assert "from pydantic import SecretStr" in settings_src
    assert "from pydantic_settings import BaseSettings, SettingsConfigDict" in settings_src
    assert "KEYCLOAK_CLIENT_SECRET: SecretStr" in settings_src
    assert "JWT_SECRET: SecretStr" in settings_src
    assert "MONGO_URI: str" in settings_src
    assert "os.environ" not in settings_src


def test_oidc_routes_read_client_secret_via_settings(tmp_path):
    ctx = _ctx_from_fixture("auth-oidc.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    oidc_src = (tmp_path / "routes" / "oidc_routes.py").read_text()
    assert "settings.KEYCLOAK_CLIENT_SECRET.get_secret_value()" in oidc_src
    assert "os.environ" not in oidc_src


def test_oidc_callback_redirects_with_code_not_token(tmp_path):
    ctx = _ctx_from_fixture("auth-oidc.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    oidc_src = (tmp_path / "routes" / "oidc_routes.py").read_text()
    exchange_src = (tmp_path / "routes" / "external_login.py").read_text()
    assert "?code={code}" in oidc_src
    assert "?token=" not in oidc_src
    assert '@router.post("/auth/exchange")' in exchange_src
    assert "redeem_login_code(code)" in exchange_src
    assert 'issue_login_code(str(record["id"]), "users", "mongo")' in oidc_src


def test_oidc_callback_uses_repository_not_raw_datastore(tmp_path):
    """Sign-in goes through the shared provisioning runtime over the collection repository,
    so the callback is datastore-agnostic instead of hardcoding the Mongo client."""
    ctx = _ctx_from_fixture("auth-oidc.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    oidc_src = (tmp_path / "routes" / "oidc_routes.py").read_text()
    assert "get_database" not in oidc_src
    assert "insert_one" not in oidc_src and "find_one" not in oidc_src
    assert "from dependencies.repositories import repository" in oidc_src
    assert '_users_keycloak_binding.sign_in(claims, repository, "users")' in oidc_src


def test_oidc_login_codes_stored_in_collection_datastore(tmp_path):
    ctx = _ctx_from_fixture("auth-oidc.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    store_src = (tmp_path / "dependencies" / "login_codes.py").read_text()
    # auth-oidc.yaml is a Mongo app: only the Mongo backend is emitted, atomically consumed.
    assert "find_one_and_delete" in store_src
    assert '"mongo": _MongoLoginCodes()' in store_src
    assert "_SqlLoginCodes" not in store_src


def test_oidc_pkce_off_by_default_omits_pkce_fields(tmp_path):
    plain = tmp_path / "plain"
    gen = FastAPIGenerator()
    gen.generate(_ctx_from_fixture("auth-oidc.yaml"), plain)
    oidc_src = (plain / "routes" / "oidc_routes.py").read_text()
    assert "code_challenge" not in oidc_src
    assert "code_verifier" not in oidc_src
    assert "pkce_verifier" not in oidc_src
    assert "import hashlib" not in oidc_src
    assert 'params["state"] = state' in oidc_src
    assert '"users_keycloak_state"' in oidc_src


def test_oidc_pkce_emits_challenge_and_verifier(tmp_path):
    gen = FastAPIGenerator()
    gen.generate(_ctx_from_fixture("auth-oidc-pkce.yaml"), tmp_path)
    oidc_src = (tmp_path / "routes" / "oidc_routes.py").read_text()
    assert "import base64" in oidc_src and "import hashlib" in oidc_src
    assert 'params["code_challenge_method"] = "S256"' in oidc_src
    assert "hashlib.sha256(verifier.encode()).digest()" in oidc_src
    assert 'response.set_cookie(\n        "users_keycloak_pkce_verifier"' in oidc_src
    assert 'verifier = request.cookies.get("users_keycloak_pkce_verifier")' in oidc_src
    assert '_token_data["code_verifier"] = verifier' in oidc_src
    assert 'detail="Missing PKCE verifier"' in oidc_src


def test_oidc_dpop_off_by_default_is_byte_identical(tmp_path):
    plain = tmp_path / "plain"
    gen = FastAPIGenerator()
    gen.generate(_ctx_from_fixture("auth-oidc.yaml"), plain)
    oidc_src = (plain / "routes" / "oidc_routes.py").read_text()
    assert "DPoP" not in oidc_src
    assert "_dpop_proof" not in oidc_src
    assert "dpop+jwt" not in oidc_src
    assert "import jwt" not in oidc_src
    assert 'headers={"Authorization": f"Bearer' in oidc_src


def test_oidc_dpop_emits_proof_and_binds_token_and_userinfo(tmp_path):
    gen = FastAPIGenerator()
    gen.generate(_ctx_from_fixture("auth-oidc-dpop.yaml"), tmp_path)
    oidc_src = (tmp_path / "routes" / "oidc_routes.py").read_text()
    settings_src = (tmp_path / "settings.py").read_text()
    dpop_src = (tmp_path / "dependencies" / "dpop.py").read_text()
    assert "KEYCLOAK_DPOP_PRIVATE_KEY: SecretStr" in settings_src
    assert "DPoPProofFactory.from_pem" in oidc_src
    assert "request_with_dpop(" in oidc_src
    assert "ec.generate_private_key" not in oidc_src
    assert 'headers={"typ": "dpop+jwt", "jwk": self.public_jwk}' in dpop_src
    assert 'f"DPoP {token_data[\'access_token\']}"' in oidc_src
    assert 'access_token=token_data["access_token"]' in oidc_src
    assert 'token_data.get("token_type", "").lower() != "dpop"' in oidc_src
    assert 'headers={"Authorization": f"Bearer' not in oidc_src


def test_oidc_login_codes_use_sql_backend_for_sql_identity(tmp_path):
    ctx = _ctx_from_fixture("auth-oidc-sql.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    store_src = (tmp_path / "dependencies" / "login_codes.py").read_text()
    assert '"sql": _SqlLoginCodes()' in store_src
    assert "_MongoLoginCodes" not in store_src
    assert "metadata" in store_src and "returning(" in store_src
    oidc_src = (tmp_path / "routes" / "oidc_routes.py").read_text()
    assert 'issue_login_code(str(record["id"]), "users", "sql")' in oidc_src


def test_shared_service_provider_defined_exactly_once(tmp_path):
    """Two controllers sharing the same service yield a single provider callable."""
    ctx = _ctx_from_fixture("shared-service.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    services_src = (tmp_path / "dependencies" / "services.py").read_text()
    assert services_src.count("get_posts_service") == 1


def test_shared_service_route_module_imports_provider(tmp_path):
    """The route module for the shared collection imports the shared service provider."""
    ctx = _ctx_from_fixture("shared-service.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    route_src = (tmp_path / "routes" / "posts.py").read_text()
    assert "from dependencies.services import get_posts_service" in route_src


def test_public_only_routes_omit_dead_auth_imports(tmp_path):
    """A route file with no authenticated routes must not import require_principal
    or _principal_has_role even when auth is globally enabled."""
    ctx = _ctx_from_fixture("roles-access.yaml")
    gen = FastAPIGenerator()
    gen.generate(ctx, tmp_path)
    # posts controller has public access for list/get; role-gated for write ops
    # users controller has auth required routes
    users_src = (tmp_path / "routes" / "users.py").read_text()
    assert "require_principal" in users_src

    # basic-crud has no auth at all; check that auth imports are absent
    ctx_no_auth = _ctx_from_fixture("basic-crud.yaml")
    gen2 = FastAPIGenerator()
    out2 = tmp_path / "no-auth"
    gen2.generate(ctx_no_auth, out2)
    posts_src = (out2 / "routes" / "posts.py").read_text()
    assert "require_principal" not in posts_src
    assert "_principal_has_role" not in posts_src


def test_build_settings_fields_skips_saml_provider_client_secret():
    oidc = IROIDCProvider(name="keycloak", client_id="app", client_secret="s3cr3t", trust="app")
    saml = IRSAMLProvider(name="corp-saml")
    auth = AuthConfig(
        enabled=True,
        identity_collections=[],
        has_password_auth=False,
        has_api_key_auth=False,
        has_oidc_auth=True,
        has_app_oidc_auth=True,
        providers={"keycloak": oidc, "corp-saml": saml},
    )
    ctx = CompileContext(
        app=AppConfig(base_path="/api", api_version="v1"),
        models=[],
        routes=[],
        auth=auth,
        datastores={},
        collections={},
    )
    fields = build_settings_fields(ctx)
    env_names = {f.env_name for f in fields}
    assert "KEYCLOAK_CLIENT_SECRET" in env_names
    assert not any("SAML" in name and "SECRET" in name for name in env_names)


# --- BUG 1 + BUG 2: generated route model_dump modes ---


def test_generated_create_route_uses_json_mode_without_exclude_unset(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    FastAPIGenerator().generate(ctx, tmp_path)
    src = (tmp_path / "routes" / "posts.py").read_text()
    assert 'model_dump(mode="json")' in src
    assert 'svc.create(payload.model_dump(mode="json"))' in src


def test_generated_update_route_uses_json_mode_with_exclude_unset(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    FastAPIGenerator().generate(ctx, tmp_path)
    src = (tmp_path / "routes" / "posts.py").read_text()
    assert 'model_dump(mode="json", exclude_unset=True)' in src
    assert 'svc.update(id, payload.model_dump(mode="json", exclude_unset=True))' in src


def test_generated_repo_match_filter_mirrors_runtime_semantics(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    FastAPIGenerator().generate(ctx, tmp_path)
    ops_src = (tmp_path / "repositories" / "_ops.py").read_text()
    assert "from bson import ObjectId" in ops_src
    assert "from bson.errors import InvalidId" in ops_src
    assert "$or" in ops_src
    assert "ObjectId(document_id)" in ops_src
    assert "InvalidId" in ops_src
    assert "return {self.ID_FIELD: document_id}" not in ops_src


def test_fastapi_emits_env_files(tmp_path):
    ctx_auth = _ctx_from_fixture("auth-password.yaml")
    gen = FastAPIGenerator()
    out_auth = tmp_path / "auth"
    gen.generate(ctx_auth, out_auth)
    env_content = (out_auth / ".env").read_text()
    assert (out_auth / ".env").exists()
    assert "JWT_SECRET=" in env_content
    jwt_line = next(l for l in env_content.splitlines() if l.startswith("JWT_SECRET="))
    assert len(jwt_line) > len("JWT_SECRET=")

    ctx_basic = _ctx_from_fixture("basic-crud.yaml")
    gen2 = FastAPIGenerator()
    out_basic = tmp_path / "basic"
    gen2.generate(ctx_basic, out_basic)
    basic_env = (out_basic / ".env").read_text()
    assert (out_basic / ".env").exists()
    assert "JWT_SECRET" not in basic_env

    example = (out_auth / ".env.example").read_text()
    assert (out_auth / ".env.example").exists()
    jwt_example = next(l for l in example.splitlines() if l.startswith("JWT_SECRET="))
    assert jwt_example == "JWT_SECRET=<jwt_secret>"
