from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from yaml_api_generator.generators.backend.compile_context import CompileContext, IdentityCollectionDescriptor
from yaml_api_generator.utils.strings import to_pascal_case
from ..base import TemplateBasedGenerator, RenderConfig, SingleFileRenderConfig
from ..utils import find_identity, group_by_collection, extract_identity_fields
from . import type_mapper
from yaml_api_generator.ir.when import (
    And,
    Equals,
    FieldRef,
    Not,
    NotEquals,
    Or,
    StringLiteral,
    WhenExpr,
    needs_document,
)


_BACKEND_GENERATORS = Path(__file__).parent.parent
_TEMPLATES_DIR = _BACKEND_GENERATORS / "drf" / "templates"
_SHARED_TEMPLATES_DIR = _BACKEND_GENERATORS / "shared" / "templates"


class DRFGenerator(TemplateBasedGenerator):
    def __init__(self):
        super().__init__()
        self._dir_prefix = "api"

    def generate(self, context: CompileContext, output_dir: Path) -> None:
        env = Environment(
            loader=ChoiceLoader([
                FileSystemLoader(str(_TEMPLATES_DIR)),
                FileSystemLoader(str(_SHARED_TEMPLATES_DIR)),
            ]),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        env.filters["drf_field"] = type_mapper.drf_field
        env.filters["capitalize_collection"] = to_pascal_case
        env.filters["when_to_python"] = _when_to_python
        env.tests["needs_document"] = _needs_document_test

        output_dir.mkdir(parents=True, exist_ok=True)

        collections_by_name = group_by_collection(context)

        self._render_project_scaffold(env, context, output_dir)
        self._render_serializers(env, context, collections_by_name, output_dir)
        self._render_services(env, context, collections_by_name, output_dir)
        self._render_views(env, context, collections_by_name, output_dir)
        self._render_repositories(env, context, collections_by_name, output_dir)
        self._render_authentication(env, context, output_dir)
        self._render_urls(env, context, output_dir)
        self._render_single_file(
            env, context, output_dir,
            SingleFileRenderConfig(
                template_name="requirements.txt.j2",
                output_path="requirements.txt",
            )
        )

    def _render_project_scaffold(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        project_dir = output_dir / "project"
        project_dir.mkdir(exist_ok=True)
        (project_dir / "__init__.py").write_text("")

        for template_name, filename in [
            ("settings.py.j2", "settings.py"),
            ("project_urls.py.j2", "urls.py"),
            ("asgi.py.j2", "asgi.py"),
            ("wsgi.py.j2", "wsgi.py"),
        ]:
            template = env.get_template(template_name)
            content = template.render(ctx=context)
            (project_dir / filename).write_text(content)

        template = env.get_template("manage.py.j2")
        (output_dir / "manage.py").write_text(template.render())

    def _render_serializers(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        self._render_collection_based(
            env, context, collections_by_name, output_dir,
            RenderConfig(
                template_name="serializers.py.j2",
                output_subdir="serializers",
                context_builder=lambda col_name, col_data, ctx: {
                    "models": col_data["models"],
                },
                should_render=lambda col_name, col_data, ctx: bool(col_data["models"]),
            )
        )

    def _render_services(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        self._render_collection_based(
            env, context, collections_by_name, output_dir,
            RenderConfig(
                template_name="service.py.j2",
                output_subdir="services",
                import_class_suffix="Service",
                context_builder=self._build_service_context,
                additional_files=[("exceptions.py.j2", "exceptions.py")],
            )
        )

    def _build_service_context(self, col_name: str, col_data: dict, context: CompileContext) -> dict:
        identity = find_identity(context, col_name)
        is_identity = identity is not None

        return {
            "collection_name": col_name,
            "is_async": True,
            "is_identity_collection": is_identity,
            "password_via": is_identity and identity.has_password,
            "identity_fields": extract_identity_fields(context, col_name),
            "import_prefix": "api.repositories",
            "auth_import_prefix": "api.authentication.auth",
            "service_import_prefix": "api.services",
        }

    def _render_views(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        self._render_collection_based(
            env, context, collections_by_name, output_dir,
            RenderConfig(
                template_name="views.py.j2",
                output_subdir="views",
                import_pattern="from .{col_name} import {class_name}ListView, {class_name}DetailView",
                context_builder=lambda col_name, col_data, ctx: {
                    "ctx": ctx,
                    "collection_name": col_name,
                    "routes": col_data["routes"],
                    "model_index": {m.name: m for m in col_data["models"]},
                    "auth": ctx.auth,
                },
                should_render=lambda col_name, col_data, ctx: bool(col_data["routes"]),
            )
        )

        if context.auth.has_password_auth:
            views_dir = output_dir / self.dir_prefix / "views"
            login_template = env.get_template("login_views.py.j2")
            login_content = login_template.render(auth=context.auth)
            (views_dir / "login.py").write_text(login_content)

    def _render_repositories(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        self._render_collection_based(
            env, context, collections_by_name, output_dir,
            RenderConfig(
                template_name="repository.py.j2",
                output_subdir="repositories",
                import_class_suffix="Repository",
                context_builder=lambda col_name, col_data, ctx: {
                    "collection_name": col_name,
                    "id_field": ctx.collections[col_name]["id_field"],
                    "id_field_format": ctx.collections[col_name]["id_format"],
                    "custom_operations": ctx.repository_operations.get(col_name, []),
                },
            )
        )

    def _render_authentication(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        files = [("mongodb.py.j2", "mongodb.py")]
        init_imports = ["from .mongodb import get_database, connect_db"]

        if context.auth.enabled:
            files.append(("auth.py.j2", "auth.py"))
            init_imports.append("from .auth import resolve_principal")

        if context.auth.has_password_auth:
            files.append(("jwt_utils.py.j2", "jwt_utils.py"))
            init_imports.append("from .jwt_utils import create_jwt_token, decode_jwt_token")

        self._render_directory(
            env, context, output_dir,
            subdir="authentication",
            files=files,
            init_imports=init_imports,
        )

    def _render_urls(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        api_dir = output_dir / self.dir_prefix
        api_dir.mkdir(parents=True, exist_ok=True)

        template = env.get_template("api_urls.py.j2")
        (api_dir / "urls.py").write_text(template.render(collections=context.collections, auth=context.auth))

        (api_dir / "__init__.py").write_text("")

        apps_template = env.get_template("apps.py.j2")
        (api_dir / "apps.py").write_text(apps_template.render())


def _operand_to_python(expr: WhenExpr) -> str:
    if isinstance(expr, StringLiteral):
        return f'"{expr.value}"'
    if isinstance(expr, FieldRef):
        if expr.root == "principal":
            if len(expr.path) == 1 and expr.path[0] == "sub":
                return 'principal.get("sub")'
            if len(expr.path) >= 2 and expr.path[0] == "record":
                return f'principal.get("record", {{}}).get("{expr.path[1]}")'
        elif expr.root == "document":
            if len(expr.path) == 1:
                return f'document.get("{expr.path[0]}")'
    return "None"


def _when_to_python(expr: WhenExpr) -> str:
    if isinstance(expr, Equals):
        return f"{_operand_to_python(expr.left)} == {_operand_to_python(expr.right)}"
    if isinstance(expr, NotEquals):
        return f"{_operand_to_python(expr.left)} != {_operand_to_python(expr.right)}"
    if isinstance(expr, And):
        return f"({_when_to_python(expr.left)} and {_when_to_python(expr.right)})"
    if isinstance(expr, Or):
        return f"({_when_to_python(expr.left)} or {_when_to_python(expr.right)})"
    if isinstance(expr, Not):
        return f"(not {_when_to_python(expr.operand)})"
    return "False"


def _needs_document_test(expr: WhenExpr) -> bool:
    return needs_document(expr)
