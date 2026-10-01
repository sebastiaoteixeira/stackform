from pathlib import Path

from jinja2 import Environment

from yaml_api_generator.generators.backend.compile_context import CompileContext, IdentityCollectionDescriptor
from yaml_api_generator.utils.strings import to_pascal_case
from ..base import TemplateBasedGenerator, RenderConfig, SingleFileRenderConfig, template_environment
from ..utils import (
    extract_identity_fields,
    find_identity,
    group_by_collection,
    pagination_config,
    runtime_module_source,
)
from ..validation import (
    reject_cookie_delivery,
    reject_dpop,
    reject_file_fields,
    reject_idp_trust,
    reject_pkce,
    reject_session_refresh,
    reject_undeclared_repository_operations,
    reject_unsigned_session_algorithm,
    validate_datastore_layout,
)
from . import type_mapper
from ..fastapi import access_filters
from .settings_builder import build_drf_settings_fields
from yaml_api_generator.ir.when import (
    And,
    Equals,
    FieldRef,
    In,
    Not,
    NotEquals,
    NotIn,
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
        validate_datastore_layout(context, "drf")
        reject_cookie_delivery(context, "drf")
        reject_dpop(context, "drf")
        reject_file_fields(context, "drf")
        reject_idp_trust(context, "drf")
        reject_session_refresh(context, "drf")
        reject_pkce(context, "drf")
        reject_unsigned_session_algorithm(context)
        reject_undeclared_repository_operations(context)
        env = template_environment(_TEMPLATES_DIR, _SHARED_TEMPLATES_DIR)
        env.globals["settings_module"] = f"{self.dir_prefix}.settings"
        env.filters["drf_field"] = type_mapper.drf_field
        env.filters["capitalize_collection"] = to_pascal_case
        env.filters["rule_to_python"] = _rule_to_python
        env.filters["py_literal"] = access_filters.py_literal
        env.filters["pagination_config"] = pagination_config
        env.filters["request_symbol_binding"] = access_filters.request_symbol_binding
        env.filters["role_hierarchies_py"] = access_filters.role_hierarchies_py
        env.filters["int"] = int
        env.tests["needs_document"] = _needs_document_test
        env.tests["needs_document_rule"] = access_filters.needs_document_rule
        env.tests["needs_current_document_rule"] = (
            access_filters.needs_current_document_rule
        )
        env.tests["needs_post_fetch"] = access_filters.needs_post_fetch
        env.tests["unconditional"] = _is_unconditional

        output_dir.mkdir(parents=True, exist_ok=True)
        api_dir = output_dir / self.dir_prefix
        api_dir.mkdir(parents=True, exist_ok=True)
        (api_dir / "conflicts.py").write_text(
            env.get_template("conflicts.py.jinja").render()
        )

        collections_by_name = group_by_collection(context)

        self._render_settings(env, context, output_dir)
        self._render_project_scaffold(env, context, output_dir)
        self._render_serializers(env, context, collections_by_name, output_dir)
        self._render_services(env, context, collections_by_name, output_dir)
        self._render_service_inputs(env, context, output_dir)
        (api_dir / "pagination.py").write_text(
            runtime_module_source("pagination")
        )
        self._render_views(env, context, collections_by_name, output_dir)
        self._render_repositories(env, context, collections_by_name, output_dir)
        self._render_authentication(env, context, output_dir)
        self._render_urls(env, context, output_dir)
        if context.session.uses_asymmetric:
            self._render_single_file(
                env, context, output_dir,
                SingleFileRenderConfig(
                    template_name="jwks_views.py.jinja",
                    output_path=f"{self.dir_prefix}/views/jwks.py",
                )
            )
        self._render_single_file(
            env, context, output_dir,
            SingleFileRenderConfig(
                template_name="requirements.txt.jinja",
                output_path="requirements.txt",
            )
        )

    def _render_service_inputs(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        self._render_single_file(
            env,
            context,
            output_dir,
            SingleFileRenderConfig(
                template_name="service_inputs.py.jinja",
                output_path=f"{self.dir_prefix}/service_inputs.py",
            ),
        )

    def _render_settings(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        api_dir = output_dir / self.dir_prefix
        api_dir.mkdir(parents=True, exist_ok=True)
        template = env.get_template("api_settings.py.jinja")
        content = template.render(settings_fields=build_drf_settings_fields(context))
        (api_dir / "settings.py").write_text(content)

    def _render_project_scaffold(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        project_dir = output_dir / "project"
        project_dir.mkdir(exist_ok=True)
        (project_dir / "__init__.py").write_text("")

        for template_name, filename in [
            ("settings.py.jinja", "settings.py"),
            ("project_urls.py.jinja", "urls.py"),
            ("asgi.py.jinja", "asgi.py"),
            ("wsgi.py.jinja", "wsgi.py"),
        ]:
            template = env.get_template(template_name)
            content = template.render(ctx=context)
            (project_dir / filename).write_text(content)

        template = env.get_template("manage.py.jinja")
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
                template_name="serializers.py.jinja",
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
                template_name="service.py.jinja",
                output_subdir="services",
                import_class_suffix="Service",
                context_builder=self._build_service_context,
                additional_files=[("exceptions.py.jinja", "exceptions.py")],
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
                template_name="views.py.jinja",
                output_subdir="views",
                generate_init_imports=False,
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

        if context.auth.has_password_auth:
            views_dir = output_dir / self.dir_prefix / "views"
            login_template = env.get_template("login_views.py.jinja")
            login_content = login_template.render(auth=context.auth)
            (views_dir / "login.py").write_text(login_content)

        handler_routes = [
            route
            for route in context.routes
            if route.collection is None and route.handler is not None
        ]
        if handler_routes:
            views_dir = output_dir / self.dir_prefix / "views"
            views_dir.mkdir(parents=True, exist_ok=True)
            (views_dir / "_handlers.py").write_text(
                env.get_template("handler_views.py.jinja").render(
                    routes=handler_routes,
                    auth=context.auth,
                )
            )

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
                    "id_field": ctx.collections[col_name]["id_field"],
                    "id_field_format": ctx.collections[col_name]["id_format"],
                    "custom_operations": ctx.repository_operations.get(col_name, []),
                    "conflict_import": "api.conflicts",
                    "pagination_import": "api.pagination",
                },
            )
        )

    def _render_authentication(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        files = [("mongodb.py.jinja", "mongodb.py")]
        init_imports = ["from .mongodb import get_database, connect_db"]

        if context.auth.enabled:
            files.append(("auth.py.jinja", "auth.py"))
            init_imports.append("from .auth import resolve_principal")

        if context.auth.uses_jwt:
            files.append(("jwt_utils.py.jinja", "jwt_utils.py"))
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

        template = env.get_template("api_urls.py.jinja")
        collections_with_routes = sorted(
            {route.collection for route in context.routes if route.collection}
        )
        (api_dir / "urls.py").write_text(
            template.render(
                collections=collections_with_routes,
                routes=context.routes,
                auth=context.auth,
            )
        )

        (api_dir / "__init__.py").write_text("")

        apps_template = env.get_template("apps.py.jinja")
        (api_dir / "apps.py").write_text(apps_template.render(ctx=context))


def _build_symbol_map(rule) -> dict[str, str]:
    symbol_map: dict[str, str] = {}
    if hasattr(rule, 'identity_symbols'):
        for symbol_name in rule.identity_symbols:
            symbol_map[symbol_name] = symbol_name
    if hasattr(rule, 'document_symbols'):
        for symbol_name in rule.document_symbols:
            symbol_map[symbol_name] = symbol_name
    return symbol_map


def _operand_to_python(expr: WhenExpr, symbol_map: dict[str, str]) -> str:
    if isinstance(expr, StringLiteral):
        return f'"{expr.value}"'
    if isinstance(expr, FieldRef):
        var_name = symbol_map.get(expr.root, expr.root)
        if not expr.path:
            return f'{var_name}.get("sub")'
        if len(expr.path) == 1:
            return f'{var_name}.get("{expr.path[0]}")'
        if len(expr.path) >= 2 and expr.path[0] == "record":
            return f'{var_name}.get("record", {{}}).get("{expr.path[1]}")'
        nested = ".".join(f'get("{p}")' for p in expr.path)
        return f'{var_name}.{nested}'
    return "None"


def _when_to_python(expr: WhenExpr, symbol_map: dict[str, str] | None = None) -> str:
    if symbol_map is None:
        symbol_map = {}
    if isinstance(expr, Equals):
        return f"{_operand_to_python(expr.left, symbol_map)} == {_operand_to_python(expr.right, symbol_map)}"
    if isinstance(expr, NotEquals):
        return f"{_operand_to_python(expr.left, symbol_map)} != {_operand_to_python(expr.right, symbol_map)}"
    if isinstance(expr, And):
        return f"({_when_to_python(expr.left, symbol_map)} and {_when_to_python(expr.right, symbol_map)})"
    if isinstance(expr, Or):
        return f"({_when_to_python(expr.left, symbol_map)} or {_when_to_python(expr.right, symbol_map)})"
    if isinstance(expr, Not):
        return f"(not {_when_to_python(expr.operand, symbol_map)})"
    if isinstance(expr, In):
        return f"{_operand_to_python(expr.left, symbol_map)} in {tuple(expr.values)!r}"
    if isinstance(expr, NotIn):
        return f"{_operand_to_python(expr.left, symbol_map)} not in {tuple(expr.values)!r}"
    return "False"


def _rule_to_python(rule) -> str:
    conditions: list[str] = []
    if getattr(rule, "principal", "").startswith("identity:"):
        collection = rule.principal.removeprefix("identity:")
        conditions.append(
            f'_resolved_principal.get("identity_collection") == "{collection}"'
        )
    if getattr(rule, "required_role", None) is not None:
        conditions.append(f'_principal_has_role(_resolved_principal, "{rule.required_role}")')
    if getattr(rule, "when", None) is not None:
        conditions.append(_when_to_python(rule.when, _build_symbol_map(rule)))
    if not conditions:
        return "True"
    return " and ".join(conditions)


def _needs_document_test(expr: WhenExpr) -> bool:
    return needs_document(expr)


def _is_unconditional(rule) -> bool:
    return (
        not getattr(rule, "principal", "")
        and getattr(rule, "when", None) is None
        and getattr(rule, "required_role", None) is None
    )
