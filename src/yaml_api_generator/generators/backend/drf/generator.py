from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from yaml_api_generator.generators.backend.compile_context import CompileContext, IdentityCollectionDescriptor
from ..base import CodeGenerator
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


class DRFGenerator(CodeGenerator):
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
        env.filters["capitalize_collection"] = _capitalize_collection
        env.filters["when_to_python"] = _when_to_python
        env.tests["needs_document"] = _needs_document_test

        output_dir.mkdir(parents=True, exist_ok=True)

        collections_by_name = _group_by_collection(context)

        self._render_project_scaffold(env, context, output_dir)
        self._render_serializers(env, context, collections_by_name, output_dir)
        self._render_services(env, context, collections_by_name, output_dir)
        self._render_views(env, context, collections_by_name, output_dir)
        self._render_repositories(env, context, collections_by_name, output_dir)
        self._render_authentication(env, context, output_dir)
        self._render_urls(env, context, output_dir)
        self._render_requirements(env, output_dir)

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
        serializers_dir = output_dir / "api" / "serializers"
        serializers_dir.mkdir(parents=True, exist_ok=True)

        template = env.get_template("serializers.py.j2")
        init_imports: list[str] = []

        for col_name, col_data in collections_by_name.items():
            models = col_data["models"]
            if not models:
                continue
            content = template.render(models=models)
            (serializers_dir / f"{col_name}.py").write_text(content)
            class_names = [m.name for m in models]
            init_imports.append(
                f"from .{col_name} import {', '.join(class_names)}"
            )

        init_content = "\n".join(init_imports) + "\n" if init_imports else ""
        (serializers_dir / "__init__.py").write_text(init_content)

    def _render_services(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        services_dir = output_dir / "api" / "services"
        services_dir.mkdir(parents=True, exist_ok=True)

        exc_template = env.get_template("exceptions.py.j2")
        (services_dir / "exceptions.py").write_text(exc_template.render())

        svc_template = env.get_template("service.py.j2")
        init_imports: list[str] = []

        for col_name in collections_by_name:
            identity = _find_identity(context, col_name)
            is_identity = identity is not None
            password_via = is_identity and "password" in identity.via

            identity_fields: list[str] = []
            if is_identity:
                if identity.identifier:
                    identity_fields.append(identity.identifier)
                identity_fields.extend(identity.via)

            content = svc_template.render(
                collection_name=col_name,
                is_async=False,
                is_identity_collection=is_identity,
                password_via=password_via,
                identity_fields=identity_fields,
                import_prefix="api.repositories",
                auth_import_prefix="api.authentication.auth",
                service_import_prefix="api.services",
            )
            (services_dir / f"{col_name}.py").write_text(content)
            class_name = _capitalize_collection(col_name)
            init_imports.append(
                f"from .{col_name} import {class_name}Service"
            )

        init_content = "\n".join(init_imports) + "\n" if init_imports else ""
        (services_dir / "__init__.py").write_text(init_content)

    def _render_views(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        views_dir = output_dir / "api" / "views"
        views_dir.mkdir(parents=True, exist_ok=True)

        template = env.get_template("views.py.j2")
        init_imports: list[str] = []

        for col_name, col_data in collections_by_name.items():
            routes = col_data["routes"]
            if not routes:
                continue
            model_index = {m.name: m for m in col_data["models"]}
            content = template.render(
                ctx=context,
                collection_name=col_name,
                routes=routes,
                model_index=model_index,
                auth=context.auth,
            )
            (views_dir / f"{col_name}.py").write_text(content)
            cap = _capitalize_collection(col_name)
            init_imports.append(
                f"from .{col_name} import {cap}ListView, {cap}DetailView"
            )

        if context.auth.has_password_auth:
            login_template = env.get_template("login_views.py.j2")
            login_content = login_template.render(auth=context.auth)
            (views_dir / "login.py").write_text(login_content)

        init_content = "\n".join(init_imports) + "\n" if init_imports else ""
        (views_dir / "__init__.py").write_text(init_content)

    def _render_repositories(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        repos_dir = output_dir / "api" / "repositories"
        repos_dir.mkdir(parents=True, exist_ok=True)

        template = env.get_template("repository.py.j2")
        init_imports: list[str] = []

        for col_name in collections_by_name:
            col_info = context.collections[col_name]
            content = template.render(
                collection_name=col_name,
                id_field=col_info["id_field"],
                id_field_format=col_info["id_format"],
            )
            (repos_dir / f"{col_name}.py").write_text(content)
            class_name = _capitalize_collection(col_name)
            init_imports.append(
                f"from .{col_name} import {class_name}Repository"
            )

        init_content = "\n".join(init_imports) + "\n" if init_imports else ""
        (repos_dir / "__init__.py").write_text(init_content)

    def _render_authentication(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        auth_dir = output_dir / "api" / "authentication"
        auth_dir.mkdir(parents=True, exist_ok=True)

        mongo_template = env.get_template("mongodb.py.j2")
        (auth_dir / "mongodb.py").write_text(mongo_template.render())

        init_lines = ["from .mongodb import get_database, connect_db"]

        if context.auth.enabled:
            auth_template = env.get_template("auth.py.j2")
            content = auth_template.render(auth=context.auth)
            (auth_dir / "auth.py").write_text(content)
            init_lines.append("from .auth import resolve_principal")

        if context.auth.has_password_auth:
            jwt_template = env.get_template("jwt_utils.py.j2")
            (auth_dir / "jwt_utils.py").write_text(jwt_template.render())
            init_lines.append("from .jwt_utils import create_jwt_token, decode_jwt_token")

        init_content = "\n".join(init_lines) + "\n"
        (auth_dir / "__init__.py").write_text(init_content)

    def _render_urls(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        template = env.get_template("api_urls.py.j2")
        content = template.render(collections=context.collections, auth=context.auth)
        api_dir = output_dir / "api"
        api_dir.mkdir(parents=True, exist_ok=True)
        (api_dir / "urls.py").write_text(content)

        (api_dir / "__init__.py").write_text("")

        apps_template = env.get_template("apps.py.j2")
        (api_dir / "apps.py").write_text(apps_template.render())

    def _render_requirements(self, env: Environment, output_dir: Path) -> None:
        template = env.get_template("requirements.txt.j2")
        (output_dir / "requirements.txt").write_text(template.render())


def _capitalize_collection(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def _find_identity(
    context: CompileContext, col_name: str
) -> IdentityCollectionDescriptor | None:
    for ic in context.auth.identity_collections:
        if ic.name == col_name:
            return ic
    return None


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


def _group_by_collection(context: CompileContext) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for col_name in context.collections:
        groups[col_name] = {"models": [], "routes": []}

    for model in context.models:
        groups[model.collection]["models"].append(model)
    for route in context.routes:
        if route.collection is None:
            continue
        groups[route.collection]["routes"].append(route)

    return groups
