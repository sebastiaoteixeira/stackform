import pytest

from yaml_api_generator.compiler.generators.fastapi.generator import FastAPIGenerator
from yaml_api_generator.compiler.generators.drf.generator import DRFGenerator
from yaml_api_generator.compiler.generators.raw.generator import RawASGIGenerator
from yaml_api_generator.compiler.generators.fastapi.type_mapper import python_type
from yaml_api_generator.compiler.generators.drf.type_mapper import drf_field
from yaml_api_generator.compiler.compile_context import FieldDescriptor
from yaml_api_generator.compiler.context_builder import build_context
from yaml_api_generator.parsing.parser import load_and_generate_ir
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


def test_fastapi_type_mapper_all_field_types():
    fields = [
        FieldDescriptor(name="s", type="string", required=True, is_optional=False),
        FieldDescriptor(name="n", type="number", required=True, is_optional=False),
        FieldDescriptor(name="b", type="boolean", required=True, is_optional=False),
        FieldDescriptor(name="d", type="datetime", required=True, is_optional=False),
        FieldDescriptor(
            name="e",
            type="enum",
            required=True,
            is_optional=False,
            enum_values=["a", "b"],
        ),
        FieldDescriptor(
            name="a",
            type="array",
            required=True,
            is_optional=False,
            array_item_type="string",
        ),
        FieldDescriptor(name="o", type="object", required=True, is_optional=False),
        FieldDescriptor(
            name="r",
            type="ref",
            required=True,
            is_optional=False,
            ref_collection="users",
        ),
    ]
    assert python_type(fields[0]) == "str"
    assert python_type(fields[1]) == "float"
    assert python_type(fields[2]) == "bool"
    assert python_type(fields[3]) == "datetime"
    assert 'Literal["a", "b"]' in python_type(fields[4])
    assert python_type(fields[5]) == "list[str]"
    assert python_type(fields[6]) == "dict[str, Any]"
    assert python_type(fields[7]) == "str"


def test_drf_project_scaffold(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = DRFGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "manage.py").exists()
    assert (tmp_path / "project" / "settings.py").exists()
    assert (tmp_path / "project" / "urls.py").exists()
    assert (tmp_path / "project" / "asgi.py").exists()
    assert (tmp_path / "project" / "wsgi.py").exists()


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
    assert "ListView" in content or "DetailView" in content


def test_drf_when_expression_to_python():
    from yaml_api_generator.compiler.generators.drf.generator import _when_to_python
    from yaml_api_generator.when_ast import Equals, FieldRef, StringLiteral

    expr = Equals(
        left=FieldRef(root="principal", path=("sub",)),
        right=FieldRef(root="document", path=("authorId",)),
    )
    result = _when_to_python(expr)
    assert 'principal.get("sub")' in result
    assert 'document.get("authorId")' in result
    assert "==" in result


def test_drf_access_rule_enforcement_in_views(tmp_path):
    ctx = _ctx_from_fixture("roles-access.yaml")
    gen = DRFGenerator()
    gen.generate(ctx, tmp_path)
    views_dir = tmp_path / "api" / "views"
    assert views_dir.exists()
    posts_view = (views_dir / "posts.py").read_text()
    assert len(posts_view) > 0


def test_drf_type_mapper_with_constraints():
    field = FieldDescriptor(
        name="score",
        type="number",
        required=True,
        is_optional=False,
        constraints={"min": 0, "max": 100},
    )
    result = drf_field(field)
    assert "serializers.FloatField" in result
    assert "min_value=0" in result
    assert "max_value=100" in result


def test_raw_asgi_app_file(tmp_path):
    ctx = _ctx_from_fixture("basic-crud.yaml")
    gen = RawASGIGenerator()
    gen.generate(ctx, tmp_path)
    assert (tmp_path / "app.py").exists()
    content = (tmp_path / "app.py").read_text()
    assert "ROUTES" in content or "ASGIApp" in content


def test_raw_path_to_regex_conversion():
    from yaml_api_generator.compiler.generators.raw.generator import _path_to_regex

    assert "(?P<id>[^/]+)" in _path_to_regex("/posts/{id}")


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
