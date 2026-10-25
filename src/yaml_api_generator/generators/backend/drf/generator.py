from pathlib import Path

from jinja2 import Environment

from yaml_api_generator.generators.backend.compile_context import CompileContext, IdentityCollectionDescriptor
from yaml_api_generator.parsers.transformers.provider_validation import reject_external_login
from yaml_api_generator.utils.strings import to_pascal_case
from ..base import RenderConfig, SingleFileRenderConfig, template_environment
from ..shared_layers import SharedLayersGenerator
from ..utils import (
    find_identity,
    group_by_collection,
    pagination_config,
    MONGO_RUNTIME_MODULES,
    write_runtime_modules,
)
from ..validation import (
    reject_cookie_delivery,
    reject_file_fields,
    reject_idp_trust,
    reject_session_refresh,
    reject_unsigned_session_algorithm,
    validate_datastore_layout,
)
from ..fastapi import access_filters
from .settings_builder import build_drf_settings_fields


_BACKEND_GENERATORS = Path(__file__).parent.parent
_TEMPLATES_DIR = _BACKEND_GENERATORS / "drf" / "templates"
_SHARED_TEMPLATES_DIR = _BACKEND_GENERATORS / "shared" / "templates"
class DRFGenerator(SharedLayersGenerator):
    auth_module = "api.authentication.auth"
    asgi_application = "project.asgi:application"

    def __init__(self):
        super().__init__()
        self._dir_prefix = "api"

    def generate(self, context: CompileContext, output_dir: Path) -> None:
        validate_datastore_layout(context, "drf")
        reject_cookie_delivery(context, "drf")
        reject_external_login(context.auth.providers, "drf")
        reject_file_fields(context, "drf")
        reject_idp_trust(context, "drf")
        reject_session_refresh(context, "drf")
        reject_unsigned_session_algorithm(context)
        env = template_environment(_TEMPLATES_DIR, _SHARED_TEMPLATES_DIR)
        env.globals["settings_module"] = f"{self.dir_prefix}.settings"
        env.filters["capitalize_collection"] = to_pascal_case
        env.filters["rule_to_predicate"] = access_filters.rule_to_predicate
        env.filters["py_literal"] = access_filters.py_literal
        env.filters["pagination_config"] = pagination_config
        env.filters["request_symbol_binding"] = access_filters.request_symbol_binding
        env.filters["role_hierarchies_py"] = access_filters.role_hierarchies_py
        env.filters["int"] = int
        env.tests["needs_document_rule"] = access_filters.needs_document_rule
        env.tests["needs_current_document_rule"] = (
            access_filters.needs_current_document_rule
        )
        env.tests["needs_post_fetch"] = access_filters.needs_post_fetch
        env.tests["unconditional"] = access_filters.is_unconditional

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
        self._render_service_inputs(env, output_dir, self.dir_prefix)
        write_runtime_modules(api_dir, (
            *MONGO_RUNTIME_MODULES,
            *(("security_headers",) if context.app.security_headers else ()),
        ))
        if context.app.cors and "*" in context.app.cors.headers:
            (api_dir / "cors.py").write_text(env.get_template("cors.py.jinja").render())
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

        commands_dir = output_dir / self.dir_prefix / "management" / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir.parent / "__init__.py").write_text("")
        (commands_dir / "__init__.py").write_text("")
        (commands_dir / "runserver.py").write_text(env.get_template("runserver.py.jinja").render())

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
        api_dir = output_dir / self.dir_prefix
        (api_dir / "payloads.py").write_text(env.get_template("payloads.py.jinja").render())
        if context.dto_models:
            (api_dir / "serializers" / "_dto.py").write_text(
                env.get_template("serializers.py.jinja").render(models=context.dto_models)
            )

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
                    "auth": ctx.auth,
                    "identity": find_identity(ctx, col_name),
                },
                should_render=lambda col_name, col_data, ctx: bool(col_data["routes"]),
            )
        )

        if context.auth.login_identities:
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

        (api_dir / "urls.py").write_text(
            env.get_template("api_urls.py.jinja").render(routes=context.routes, auth=context.auth)
        )

        (api_dir / "__init__.py").write_text("")

        apps_template = env.get_template("apps.py.jinja")
        (api_dir / "apps.py").write_text(apps_template.render(ctx=context))
