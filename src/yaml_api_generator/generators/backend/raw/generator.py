import re
from pathlib import Path

from jinja2 import Environment

from yaml_api_generator.generators.backend.compile_context import (
    CompileContext,
    IdentityCollectionDescriptor,
)
from yaml_api_generator.generators.backend.builders.settings_builder import build_settings_fields
from yaml_api_generator.ir import SECRET_FIELD
from yaml_api_generator.parsers.transformers.provider_validation import reject_external_login
from yaml_api_generator.utils.strings import to_pascal_case
from ..base import SingleFileRenderConfig, template_environment
from ..shared_layers import SharedLayersGenerator
from ..utils import (
    find_identity,
    group_by_collection,
    pagination_config,
    MONGO_RUNTIME_MODULES,
    write_environment_files,
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


_BACKEND_GENERATORS = Path(__file__).parent.parent
_TEMPLATES_DIR = _BACKEND_GENERATORS / "raw" / "templates"
_SHARED_TEMPLATES_DIR = _BACKEND_GENERATORS / "shared" / "templates"
def _path_to_regex(path: str) -> str:
    """Convert /{collection}/{id} style path to regex with named groups."""
    def _replace(m: re.Match) -> str:
        return f"(?P<{m.group(1)}>[^/]+)"
    return re.sub(r"\{(\w+)\}", _replace, path)


class RawASGIGenerator(SharedLayersGenerator):
    auth_module = "dependencies.auth"

    def generate(self, context: CompileContext, output_dir: Path) -> None:
        validate_datastore_layout(context, "raw")
        reject_cookie_delivery(context, "raw")
        reject_external_login(context.auth.providers, "raw")
        reject_file_fields(context, "raw")
        reject_idp_trust(context, "raw")
        reject_session_refresh(context, "raw")
        reject_unsigned_session_algorithm(context)
        env = template_environment(_TEMPLATES_DIR, _SHARED_TEMPLATES_DIR)
        env.globals["settings_module"] = "settings"
        env.filters["path_to_regex"] = _path_to_regex
        env.filters["capitalize_collection"] = to_pascal_case
        env.filters["py_literal"] = access_filters.py_literal
        env.filters["pagination_config"] = pagination_config
        env.filters["rule_to_predicate"] = access_filters.rule_to_predicate
        env.filters["request_symbol_binding"] = access_filters.request_symbol_binding
        env.filters["role_hierarchies_py"] = access_filters.role_hierarchies_py
        env.tests["unconditional"] = access_filters.is_unconditional
        env.tests["needs_document_rule"] = access_filters.needs_document_rule
        env.tests["needs_current_document_rule"] = (
            access_filters.needs_current_document_rule
        )
        env.tests["needs_post_fetch"] = access_filters.needs_post_fetch
        env.filters["int"] = int

        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "conflicts.py").write_text(
            env.get_template("conflicts.py.jinja").render()
        )

        self._render_service_inputs(env, output_dir, "")
        write_runtime_modules(output_dir, (
            *MONGO_RUNTIME_MODULES,
            *(("security_headers",) if context.app.security_headers else ()),
        ))

        collections_by_name = group_by_collection(context)

        self._render_settings(env, context, output_dir)
        write_environment_files(env, context, output_dir)
        self._render_routes(env, context, collections_by_name, output_dir)
        if context.auth.login_identities:
            self._render_login_routes(env, context, output_dir)
        if context.session.uses_asymmetric:
            self._render_single_file(
                env, context, output_dir,
                SingleFileRenderConfig(
                    template_name="jwks_routes.py.jinja",
                    output_path="routes/jwks.py",
                )
            )
        self._render_app(env, context, output_dir)
        self._render_validation(env, context, collections_by_name, output_dir)
        self._render_services(env, context, collections_by_name, output_dir)
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
        self._render_single_file(
            env, context, output_dir,
            SingleFileRenderConfig(
                template_name="app.py.jinja",
                output_path="app.py",
                context_builder=lambda ctx: {
                    "ctx": ctx,
                    "collections": ctx.collections,
                    "routes": ctx.routes,
                },
            )
        )

    def _render_validation(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        models = [
            *(model for col_data in collections_by_name.values() for model in col_data["models"]),
            *context.dto_models,
        ]

        self._render_single_file(
            env, context, output_dir,
            SingleFileRenderConfig(
                template_name="validation.py.jinja",
                output_path="validation.py",
                context_builder=lambda ctx: {
                    "models": models,
                    "auth": ctx.auth,
                },
            )
        )

    def _render_routes(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
    ) -> None:
        routes_dir = output_dir / "routes"
        routes_dir.mkdir(parents=True, exist_ok=True)
        (routes_dir / "__init__.py").write_text("")

        for col_name, col_data in collections_by_name.items():
            if not col_data["routes"]:
                continue

            needs_auth = any(route.needs_auth for route in col_data["routes"])

            template = env.get_template("routes.py.jinja")
            content = template.render(
                collection_name=col_name,
                routes=col_data["routes"],
                needs_auth=needs_auth,
                auth=context.auth,
                identity=find_identity(context, col_name),
            )
            (routes_dir / f"{col_name}.py").write_text(content)

        handler_routes = [
            route
            for route in context.routes
            if route.collection is None and route.handler is not None
        ]
        if handler_routes:
            content = env.get_template("handler_routes.py.jinja").render(
                routes=handler_routes,
                needs_auth=any(route.needs_auth for route in handler_routes),
                auth=context.auth,
            )
            (routes_dir / "handlers.py").write_text(content)

    def _render_login_routes(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        routes_dir = output_dir / "routes"
        routes_dir.mkdir(parents=True, exist_ok=True)

        template = env.get_template("login_routes.py.jinja")
        content = template.render(ctx=context, secret=SECRET_FIELD)
        (routes_dir / "login.py").write_text(content)

    def _render_dependencies(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        files = [("mongodb.py.jinja", "mongodb.py")]
        init_imports = ["from .mongodb import get_database"]

        if context.auth.enabled:
            files.append(("auth.py.jinja", "auth.py"))
            init_imports.append("from .auth import resolve_principal")

        if context.auth.uses_jwt:
            files.append(("jwt_utils.py.jinja", "jwt_utils.py"))
            init_imports.append("from .jwt_utils import create_jwt_token, decode_jwt_token")

        self._render_directory(
            env, context, output_dir,
            subdir="dependencies",
            files=files,
            init_imports=init_imports,
        )
