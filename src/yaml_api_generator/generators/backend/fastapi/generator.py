from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from yaml_api_generator.generators.backend.compile_context import CompileContext, IdentityCollectionDescriptor
from yaml_api_generator.utils.strings import to_pascal_case, to_py_identifier
from ..base import TemplateBasedGenerator, RenderConfig, SingleFileRenderConfig
from ..utils import find_identity, group_by_collection, extract_identity_fields
from . import access_filters, type_mapper


_BACKEND_GENERATORS = Path(__file__).parent.parent
_TEMPLATES_DIR = _BACKEND_GENERATORS / "fastapi" / "templates"
_SHARED_TEMPLATES_DIR = _BACKEND_GENERATORS / "shared" / "templates"

_CRUD_ORDER = ("list", "get", "create", "update", "replace", "delete")


def _crud_operations(col_data: dict) -> list[str]:
    present = {
        route.operation
        for route in col_data["routes"]
        if route.handler is None and route.operation in _CRUD_ORDER
    }
    return [op for op in _CRUD_ORDER if op in present]


class FastAPIGenerator(TemplateBasedGenerator):
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
        env.filters["capitalize_collection"] = to_pascal_case
        env.filters["py_identifier"] = to_py_identifier
        env.filters["py_bool"] = access_filters.py_bool
        env.filters["py_literal"] = access_filters.py_literal
        env.filters["access_rule_py"] = access_filters.access_rule_py
        env.filters["role_hierarchies_py"] = access_filters.role_hierarchies_py
        env.tests["needs_post_fetch"] = access_filters.needs_post_fetch
        env.globals["needs_datetime_import"] = type_mapper.needs_datetime_import
        env.globals["needs_literal_import"] = type_mapper.needs_literal_import
        env.globals["needs_any_import"] = type_mapper.needs_any_import

        output_dir.mkdir(parents=True, exist_ok=True)

        collections_by_name = group_by_collection(context)

        self._render_app(env, context, output_dir)
        self._render_models(env, context, collections_by_name, output_dir)
        self._render_services(env, context, collections_by_name, output_dir)
        self._render_routes(env, context, collections_by_name, output_dir)
        self._render_repositories(env, context, collections_by_name, output_dir)
        self._render_dependencies(env, context, output_dir)
        self._render_single_file(
            env, context, output_dir,
            SingleFileRenderConfig(
                template_name="requirements.txt.jinja",
                output_path="requirements.txt",
            )
        )

    def _render_app(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        template = env.get_template("app.py.jinja")
        content = template.render(ctx=context)
        (output_dir / "app.py").write_text(content)

    def _render_models(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        self._render_collection_based(
            env, context, collections_by_name, output_dir,
            RenderConfig(
                template_name="models.py.jinja",
                output_subdir="models",
                context_builder=lambda col_name, col_data, ctx: {
                    "models": col_data["models"],
                    "all_fields": [f for m in col_data["models"] for f in m.fields],
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
                template_name="service.py.jinja",
                output_subdir="services",
                import_class_suffix="Service",
                context_builder=self._build_service_context,
                additional_files=[("exceptions.py.jinja", "exceptions.py")],
            )
        )

        ops_template = env.get_template("service_ops.py.jinja")
        ops_content = ops_template.render(auth=context.auth)
        (output_dir / "services" / "_ops.py").write_text(ops_content)

    def _build_service_context(self, col_name: str, col_data: dict, context: CompileContext) -> dict:
        identity = find_identity(context, col_name)
        is_identity = identity is not None

        return {
            "collection_name": col_name,
            "operations": _crud_operations(col_data),
            "is_identity_collection": is_identity,
            "password_via": is_identity and identity.has_password,
            "identity_fields": extract_identity_fields(context, col_name),
        }

    def _render_routes(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        self._render_collection_based(
            env, context, collections_by_name, output_dir,
            RenderConfig(
                template_name="routes.py.jinja",
                output_subdir="routes",
                import_pattern="from .{col_name} import router as {col_name}_router",
                context_builder=lambda col_name, col_data, ctx: {
                    "ctx": ctx,
                    "collection_name": col_name,
                    "routes": col_data["routes"],
                    "model_index": {m.name: m for m in col_data["models"]},
                    "repo_queries": {
                        op["name"]: op["query"]
                        for op in ctx.repository_operations.get(col_name, [])
                    },
                    "auth": ctx.auth,
                },
                should_render=lambda col_name, col_data, ctx: bool(col_data["routes"]),
            )
        )

        routes_dir = output_dir / "routes"
        factory_template = env.get_template("crud_factory.py.jinja")
        factory_content = factory_template.render(auth=context.auth)
        (routes_dir / "_crud_factory.py").write_text(factory_content)
        init_path = routes_dir / "__init__.py"
        existing_imports = init_path.read_text() if init_path.exists() else ""
        auth_imports = []

        if context.auth.has_password_auth:
            login_template = env.get_template("login_routes.py.jinja")
            base_prefix = context.app.base_path
            if context.app.api_version:
                base_prefix = f"{base_prefix}/{context.app.api_version}"
            login_content = login_template.render(auth=context.auth, base_prefix=base_prefix)
            (routes_dir / "login.py").write_text(login_content)
            auth_imports.append("from .login import router as login_router")

        if context.auth.has_oidc_auth:
            oidc_template = env.get_template("oidc_routes.py.jinja")
            base_prefix = context.app.base_path
            if context.app.api_version:
                base_prefix = f"{base_prefix}/{context.app.api_version}"
            oidc_content = oidc_template.render(auth=context.auth, base_prefix=base_prefix)
            (routes_dir / "oidc_routes.py").write_text(oidc_content)
            auth_imports.append("from .oidc_routes import router as oidc_router")

        if context.auth.has_saml_auth:
            saml_template = env.get_template("saml_routes.py.jinja")
            saml_content = saml_template.render(auth=context.auth)
            (routes_dir / "saml_routes.py").write_text(saml_content)
            auth_imports.append("from .saml_routes import router as saml_router")

        if auth_imports:
            init_content = existing_imports + "\n".join(auth_imports) + "\n"
            init_path.write_text(init_content)

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
                template_name="repository.py.jinja",
                output_subdir="repositories",
                import_class_suffix="Repository",
                context_builder=lambda col_name, col_data, ctx: {
                    "collection_name": col_name,
                    "operations": _crud_operations(col_data),
                    "id_field": ctx.collections[col_name]["id_field"],
                    "id_field_format": ctx.collections[col_name]["id_format"],
                    "custom_operations": ctx.repository_operations.get(col_name, []),
                },
            )
        )

        ops_template = env.get_template("repository_ops.py.jinja")
        ops_content = ops_template.render()
        (output_dir / "repositories" / "_ops.py").write_text(ops_content)

    def _render_dependencies(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        files = [("mongodb.py.jinja", "mongodb.py")]
        init_imports = ["from .mongodb import get_database"]

        if context.auth.enabled:
            files.append(("auth.py.jinja", "auth.py"))
            files.append(("when_eval.py.jinja", "when_eval.py"))
            files.append(("authorization.py.jinja", "authorization.py"))
            init_imports.append("from .auth import resolve_principal, require_principal")
            init_imports.append("from .authorization import AccessRule, authorize_pre, authorize_post")

        if context.auth.has_password_auth:
            files.append(("jwt_utils.py.jinja", "jwt_utils.py"))
            init_imports.append("from .jwt_utils import create_jwt_token, decode_jwt_token")

        self._render_directory(
            env, context, output_dir,
            subdir="dependencies",
            files=files,
            init_imports=init_imports,
        )

