from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from yaml_api_generator.generators.backend.compile_context import CompileContext, IdentityCollectionDescriptor
from yaml_api_generator.generators.backend.builders.settings_builder import build_settings_fields
from yaml_api_generator.utils.strings import to_pascal_case, to_py_identifier
from ..base import TemplateBasedGenerator, RenderConfig, SingleFileRenderConfig
from ..utils import find_identity, group_by_collection, extract_identity_fields
from . import access_filters, sql_filters, type_mapper


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
        env.filters["env_ref"] = access_filters.env_ref
        env.filters["sql_column"] = sql_filters.sql_column
        env.filters["rule_to_python"] = access_filters.rule_to_python
        env.filters["role_hierarchies_py"] = access_filters.role_hierarchies_py
        env.tests["needs_post_fetch"] = access_filters.needs_post_fetch
        env.tests["needs_document_rule"] = access_filters.needs_document_rule
        env.tests["unconditional"] = access_filters.is_unconditional
        env.globals["needs_datetime_import"] = type_mapper.needs_datetime_import
        env.globals["needs_literal_import"] = type_mapper.needs_literal_import
        env.globals["needs_any_import"] = type_mapper.needs_any_import

        output_dir.mkdir(parents=True, exist_ok=True)

        collections_by_name = group_by_collection(context)

        self._render_settings(env, context, output_dir)
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

    def _render_settings(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        template = env.get_template("settings.py.jinja")
        content = template.render(settings_fields=build_settings_fields(context))
        (output_dir / "settings.py").write_text(content)

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
                    "datastore_type": ctx.collection_datastore_type(col_name),
                    "auth": ctx.auth,
                },
                should_render=lambda col_name, col_data, ctx: bool(col_data["routes"]),
            )
        )

        routes_dir = output_dir / "routes"
        init_path = routes_dir / "__init__.py"
        resource_imports = init_path.read_text() if init_path.exists() else ""

        base_prefix = context.app.base_path
        if context.app.api_version:
            base_prefix = f"{base_prefix}/{context.app.api_version}"

        auth_imports: list[str] = []

        if context.auth.has_password_auth:
            (routes_dir / "login.py").write_text(
                env.get_template("login_routes.py.jinja").render(auth=context.auth)
            )
            auth_imports.append("from .login import router as login_router")

        if context.auth.has_oidc_auth:
            (routes_dir / "oidc_routes.py").write_text(
                env.get_template("oidc_routes.py.jinja").render(
                    auth=context.auth, base_prefix=base_prefix
                )
            )
            auth_imports.append("from .oidc_routes import router as oidc_router")

        if context.auth.has_saml_auth:
            (routes_dir / "saml_routes.py").write_text(
                env.get_template("saml_routes.py.jinja").render(auth=context.auth)
            )
            auth_imports.append("from .saml_routes import router as saml_router")

        all_router_names = [
            line.split(" as ")[1].rstrip()
            for line in (resource_imports + "\n".join(auth_imports)).splitlines()
            if " as " in line
        ]
        aggregator = self._render_api_router(all_router_names)

        init_path.write_text(
            resource_imports
            + ("\n".join(auth_imports) + "\n" if auth_imports else "")
            + aggregator
        )

    @staticmethod
    def _render_api_router(router_names: list[str]) -> str:
        lines = ["\nfrom fastapi import APIRouter\n\napi_router = APIRouter()\n"]
        lines.extend(f"api_router.include_router({name})\n" for name in router_names)
        return "".join(lines)

    def _render_repositories(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        repos_dir = output_dir / "repositories"
        repos_dir.mkdir(parents=True, exist_ok=True)

        mongo_template = env.get_template("repository.py.jinja")
        sql_template = env.get_template("repository_sql.py.jinja")
        init_imports: list[str] = []
        uses_mongo = uses_sql = False

        def generated_base(name: str) -> dict[str, str] | None:
            base = context.repository_inherits.get(name)
            if base is None:
                return None
            return {"module": f".{base}", "class_name": f"{to_pascal_case(base)}Repository"}

        # Abstract base repositories render as inheritable classes (no collection).
        for base_name, ds_type in context.repository_abstract.items():
            is_sql = ds_type in ("postgres", "postgresql")
            template = sql_template if is_sql else mongo_template
            (repos_dir / f"{base_name}.py").write_text(template.render(
                abstract=True,
                collection_name=base_name,
                operations=[],
                custom_operations=context.repository_operations.get(base_name, []),
                generated_base=generated_base(base_name),
            ))
            init_imports.append(f"from .{base_name} import {to_pascal_case(base_name)}Repository")
            uses_sql = uses_sql or is_sql
            uses_mongo = uses_mongo or not is_sql

        for col_name, col_data in collections_by_name.items():
            meta = context.collections[col_name]
            is_sql = meta.get("datastore_type") in ("postgres", "postgresql")
            template_context = {
                "collection_name": col_name,
                "operations": _crud_operations(col_data),
                "id_field": meta["id_field"],
                "id_field_format": meta["id_format"],
                "fields": meta["fields"],
                "custom_operations": ctx_ops if (ctx_ops := context.repository_operations.get(col_name, [])) else [],
                "generated_base": generated_base(col_name),
            }
            template = sql_template if is_sql else mongo_template
            (repos_dir / f"{col_name}.py").write_text(template.render(**template_context))
            init_imports.append(
                f"from .{col_name} import {to_pascal_case(col_name)}Repository"
            )
            uses_sql = uses_sql or is_sql
            uses_mongo = uses_mongo or not is_sql

        (repos_dir / "__init__.py").write_text("\n".join(init_imports) + "\n")
        if uses_mongo:
            (repos_dir / "_ops.py").write_text(env.get_template("repository_ops.py.jinja").render())
        if uses_sql:
            (repos_dir / "_sql_ops.py").write_text(
                env.get_template("repository_sql_ops.py.jinja").render()
            )

    def _render_dependencies(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        col_types = {context.collection_datastore_type(c) for c in context.collections}
        uses_sql = bool(col_types & {"postgres", "postgresql"})
        uses_mongo = bool(col_types & {"mongodb", "mongo"}) or not uses_sql

        deps_dir = output_dir / "dependencies"
        deps_dir.mkdir(parents=True, exist_ok=True)

        if uses_mongo:
            (deps_dir / "mongodb.py").write_text(
                env.get_template("mongodb.py.jinja").render(ctx=context, auth=context.auth)
            )
        if uses_sql:
            (deps_dir / "postgres.py").write_text(
                env.get_template("postgres.py.jinja").render()
            )

        init_imports: list[str] = []
        auth_files = []
        if context.auth.enabled:
            auth_files += [
                ("auth.py.jinja", "auth.py"),
                ("authorization.py.jinja", "authorization.py"),
            ]
            init_imports.append("from .auth import resolve_principal, require_principal")
            init_imports.append("from .authorization import _principal_has_role")
        if context.auth.uses_jwt:
            auth_files.append(("jwt_utils.py.jinja", "jwt_utils.py"))
            init_imports.append("from .jwt_utils import create_jwt_token, decode_jwt_token")

        for template_name, filename in auth_files:
            (deps_dir / filename).write_text(
                env.get_template(template_name).render(ctx=context, auth=context.auth)
            )

        (deps_dir / "__init__.py").write_text(
            "\n".join(init_imports) + "\n" if init_imports else ""
        )

