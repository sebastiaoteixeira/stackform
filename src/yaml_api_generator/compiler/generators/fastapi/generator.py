from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from ...compile_context import CompileContext, IdentityCollectionDescriptor
from ..base import CodeGenerator
from . import type_mapper


_TEMPLATES_DIR = Path(__file__).parent / "templates"
_SHARED_TEMPLATES_DIR = Path(__file__).parent.parent / "shared" / "templates"


class FastAPIGenerator(CodeGenerator):
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
        env.filters["python_type"] = type_mapper.python_type
        env.filters["python_annotation"] = type_mapper.python_annotation
        env.filters["capitalize_collection"] = _capitalize_collection
        env.globals["needs_datetime_import"] = type_mapper.needs_datetime_import
        env.globals["needs_literal_import"] = type_mapper.needs_literal_import
        env.globals["needs_any_import"] = type_mapper.needs_any_import

        output_dir.mkdir(parents=True, exist_ok=True)

        collections_by_name = _group_by_collection(context)

        self._render_app(env, context, output_dir)
        self._render_models(env, context, collections_by_name, output_dir)
        self._render_services(env, context, collections_by_name, output_dir)
        self._render_routes(env, context, collections_by_name, output_dir)
        self._render_repositories(env, context, collections_by_name, output_dir)
        self._render_dependencies(env, context, output_dir)
        self._render_requirements(env, output_dir)

    def _render_app(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        template = env.get_template("app.py.j2")
        content = template.render(ctx=context)
        (output_dir / "app.py").write_text(content)

    def _render_models(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        models_dir = output_dir / "models"
        models_dir.mkdir(exist_ok=True)

        template = env.get_template("models.py.j2")
        init_imports: list[str] = []

        for col_name, col_data in collections_by_name.items():
            models = col_data["models"]
            if not models:
                continue
            all_fields = [f for m in models for f in m.fields]
            content = template.render(models=models, all_fields=all_fields)
            (models_dir / f"{col_name}.py").write_text(content)
            class_names = [m.name for m in models]
            init_imports.append(
                f"from .{col_name} import {', '.join(class_names)}"
            )

        init_content = "\n".join(init_imports) + "\n" if init_imports else ""
        (models_dir / "__init__.py").write_text(init_content)

    def _render_services(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        services_dir = output_dir / "services"
        services_dir.mkdir(exist_ok=True)

        exc_template = env.get_template("exceptions.py.j2")
        (services_dir / "exceptions.py").write_text(exc_template.render())

        svc_template = env.get_template("service.py.j2")
        init_imports: list[str] = []

        for col_name in collections_by_name:
            identity = _find_identity(context, col_name)
            is_identity = identity is not None
            password_via = is_identity and identity.has_password

            identity_fields: list[str] = []
            if is_identity:
                seen: set[str] = set()
                for b in identity.bindings:
                    if b.identifier not in seen:
                        identity_fields.append(b.identifier)
                        seen.add(b.identifier)

            content = svc_template.render(
                collection_name=col_name,
                is_async=True,
                is_identity_collection=is_identity,
                password_via=password_via,
                identity_fields=identity_fields,
                import_prefix="repositories",
                auth_import_prefix="dependencies.auth",
                service_import_prefix="services",
            )
            (services_dir / f"{col_name}.py").write_text(content)
            class_name = _capitalize_collection(col_name)
            init_imports.append(
                f"from .{col_name} import {class_name}Service"
            )

        init_content = "\n".join(init_imports) + "\n" if init_imports else ""
        (services_dir / "__init__.py").write_text(init_content)

    def _render_routes(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        routes_dir = output_dir / "routes"
        routes_dir.mkdir(exist_ok=True)

        template = env.get_template("routes.py.j2")
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
            (routes_dir / f"{col_name}.py").write_text(content)
            init_imports.append(
                f"from .{col_name} import router as {col_name}_router"
            )

        if context.auth.has_password_auth:
            login_template = env.get_template("login_routes.py.j2")
            login_content = login_template.render(auth=context.auth)
            (routes_dir / "login.py").write_text(login_content)
            init_imports.append(
                "from .login import router as login_router"
            )

        if context.auth.has_oidc_auth:
            oidc_template = env.get_template("oidc_routes.py.j2")
            oidc_content = oidc_template.render(auth=context.auth)
            (routes_dir / "oidc_routes.py").write_text(oidc_content)
            init_imports.append(
                "from .oidc_routes import router as oidc_router"
            )

        if context.auth.has_saml_auth:
            saml_template = env.get_template("saml_routes.py.j2")
            saml_content = saml_template.render(auth=context.auth)
            (routes_dir / "saml_routes.py").write_text(saml_content)
            init_imports.append(
                "from .saml_routes import router as saml_router"
            )

        init_content = "\n".join(init_imports) + "\n" if init_imports else ""
        (routes_dir / "__init__.py").write_text(init_content)

    def _render_repositories(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        repos_dir = output_dir / "repositories"
        repos_dir.mkdir(exist_ok=True)

        template = env.get_template("repository.py.j2")
        init_imports: list[str] = []

        for col_name, col_data in collections_by_name.items():
            col_info = context.collections[col_name]
            content = template.render(
                collection_name=col_name,
                id_field=col_info["id_field"],
                id_field_format=col_info["id_format"],
            )
            (repos_dir / f"{col_name}.py").write_text(content)
            class_name = "".join(p.capitalize() for p in col_name.split("_"))
            init_imports.append(
                f"from .{col_name} import {class_name}Repository"
            )

        init_content = "\n".join(init_imports) + "\n" if init_imports else ""
        (repos_dir / "__init__.py").write_text(init_content)

    def _render_dependencies(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        deps_dir = output_dir / "dependencies"
        deps_dir.mkdir(exist_ok=True)

        mongo_template = env.get_template("mongodb.py.j2")
        (deps_dir / "mongodb.py").write_text(mongo_template.render())

        init_lines = ["from .mongodb import get_database"]

        if context.auth.enabled:
            auth_template = env.get_template("auth.py.j2")
            content = auth_template.render(auth=context.auth)
            (deps_dir / "auth.py").write_text(content)
            init_lines.append("from .auth import resolve_principal")

        if context.auth.has_password_auth:
            jwt_template = env.get_template("jwt_utils.py.j2")
            (deps_dir / "jwt_utils.py").write_text(jwt_template.render())
            init_lines.append("from .jwt_utils import create_jwt_token, decode_jwt_token")

        init_content = "\n".join(init_lines) + "\n"
        (deps_dir / "__init__.py").write_text(init_content)

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
