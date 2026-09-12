from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from yaml_api_generator.generators.backend.compile_context import CompileContext, IdentityCollectionDescriptor
from yaml_api_generator.generators.backend.builders.settings_builder import build_settings_fields, generated_secret_values
from yaml_api_generator.utils.strings import to_pascal_case, to_py_identifier
from ..base import TemplateBasedGenerator, RenderConfig, SingleFileRenderConfig
from ..utils import (
    extract_identity_fields,
    find_identity,
    group_by_collection,
    pagination_config,
    runtime_module_source,
)
from ..validation import reject_unsigned_session_algorithm, validate_datastore_layout
from . import access_filters, sql_filters, type_mapper


_BACKEND_GENERATORS = Path(__file__).parent.parent

_TEMPLATES_DIR = _BACKEND_GENERATORS / "fastapi" / "templates"
_SHARED_TEMPLATES_DIR = _BACKEND_GENERATORS / "shared" / "templates"
_STATIC_DIR = _BACKEND_GENERATORS / "fastapi" / "static"
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
        validate_datastore_layout(context, "fastapi")
        reject_unsigned_session_algorithm(context)
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
        env.globals["settings_module"] = "settings"
        env.filters["py_literal"] = access_filters.py_literal
        env.filters["pagination_config"] = pagination_config
        env.filters["sql_column"] = sql_filters.sql_column
        env.filters["rule_to_python"] = access_filters.rule_to_python
        env.filters["role_hierarchies_py"] = access_filters.role_hierarchies_py
        env.filters["request_symbol_binding"] = access_filters.request_symbol_binding
        env.tests["needs_post_fetch"] = access_filters.needs_post_fetch
        env.tests["needs_document_rule"] = access_filters.needs_document_rule
        env.tests["needs_request_rule"] = access_filters.needs_request_rule
        env.tests["unconditional"] = access_filters.is_unconditional
        env.globals["needs_datetime_import"] = type_mapper.needs_datetime_import
        env.globals["needs_literal_import"] = type_mapper.needs_literal_import
        env.globals["needs_any_import"] = type_mapper.needs_any_import

        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "conflicts.py").write_text(
            env.get_template("conflicts.py.jinja").render()
        )

        collections_by_name = group_by_collection(context)

        self._render_settings(env, context, output_dir)
        self._render_env(env, context, output_dir)
        self._render_app(env, context, output_dir)
        self._render_models(env, context, collections_by_name, output_dir)
        self._render_dtos(env, context, output_dir)
        self._render_services(env, context, collections_by_name, output_dir)
        self._render_service_inputs(env, context, output_dir)
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

    def _render_service_inputs(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        self._render_single_file(
            env,
            context,
            output_dir,
            SingleFileRenderConfig(
                template_name="service_inputs.py.jinja",
                output_path="dependencies/service_inputs.py",
            ),
        )

    def _render_settings(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        template = env.get_template("settings.py.jinja")
        content = template.render(settings_fields=build_settings_fields(context))
        (output_dir / "settings.py").write_text(content)

    def _render_env(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        fields = build_settings_fields(context)
        secret_values = generated_secret_values(fields)
        env_values = {
            f.env_name: secret_values.get(f.env_name, f.default or "")
            for f in fields
        }
        example_values = {
            f.env_name: f"<{f.env_name.lower()}>" if f.secret else (f.default or "")
            for f in fields
        }
        template = env.get_template("env.jinja")
        (output_dir / ".env").write_text(template.render(settings_fields=fields, values=env_values))
        (output_dir / ".env.example").write_text(template.render(settings_fields=fields, values=example_values))

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

    def _render_dtos(
        self, env: Environment, context: CompileContext, output_dir: Path
    ) -> None:
        if not context.dto_models:
            return
        models_dir = output_dir / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        content = env.get_template("models.py.jinja").render(
            models=context.dto_models,
            all_fields=[f for m in context.dto_models for f in m.fields],
        )
        (models_dir / "_dto.py").write_text(content)

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

    @staticmethod
    def _service_group(route_service: str | None, services: dict) -> str | None:
        """Resolve the repository/service-group name backing a route's service.

        For expanded flat keys like 'list-posts', the IRService carries the
        repository name directly. Falling back to the part after the first dash
        handles edge cases where the service isn't in the index.
        """
        if route_service is None:
            return None
        ir_svc = services.get(route_service)
        if ir_svc is not None and ir_svc.repository:
            return ir_svc.repository
        # Fallback: strip the operation prefix (e.g. "list-posts" → "posts")
        if "-" in route_service:
            return route_service.split("-", 1)[1]
        return route_service

    def _build_routes_context(
        self, col_name: str, col_data: dict, ctx: CompileContext
    ) -> dict:
        service_groups = list(dict.fromkeys(
            g
            for route in col_data["routes"]
            if (g := self._service_group(route.service, ctx.services)) is not None
        ))
        return {
            "ctx": ctx,
            "collection_name": col_name,
            "service_groups": service_groups,
            "routes": col_data["routes"],
            "model_index": {m.name: m for m in col_data["models"]},
            "repo_queries": {
                op["name"]: op["query"]
                for op in ctx.repository_operations.get(col_name, [])
            },
            "datastore_type": ctx.collection_datastore_type(col_name),
            "auth": ctx.auth,
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
                context_builder=self._build_routes_context,
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

        if context.auth.uses_jwt and context.session.uses_asymmetric:
            (routes_dir / "jwks.py").write_text(
                env.get_template("jwks_routes.py.jinja").render()
            )

        handler_routes = [
            route
            for route in context.routes
            if route.collection is None and route.handler is not None
        ]
        if handler_routes:
            (routes_dir / "_handlers.py").write_text(
                env.get_template("handler_routes.py.jinja").render(
                    routes=handler_routes,
                    auth=context.auth,
                )
            )
            auth_imports.append("from ._handlers import router as handlers_router")

        if context.auth.has_password_auth:
            (routes_dir / "login.py").write_text(
                env.get_template("login_routes.py.jinja").render(
                    auth=context.auth, ctx=context
                )
            )
            auth_imports.append("from .login import router as login_router")

        if context.session.uses_cookie:
            (routes_dir / "session.py").write_text(
                env.get_template("session_routes.py.jinja").render()
            )
            auth_imports.append("from .session import router as session_router")

        if context.auth.has_app_oidc_auth:
            (routes_dir / "oidc_routes.py").write_text(
                env.get_template("oidc_routes.py.jinja").render(
                    auth=context.auth, base_prefix=base_prefix, ctx=context
                )
            )
            auth_imports.append("from .oidc_routes import router as oidc_router")

        if context.auth.has_saml_auth:
            (routes_dir / "saml_routes.py").write_text(
                env.get_template("saml_routes.py.jinja").render(
                    auth=context.auth, ctx=context
                )
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
                env.get_template("postgres.py.jinja").render(ctx=context)
            )
        if context.auth.has_app_oidc_auth:
            (deps_dir / "login_codes.py").write_text(
                env.get_template("login_codes.py.jinja").render(auth=context.auth)
            )
        if context.auth.has_idp_auth:
            (deps_dir / "idp_auth.py").write_text(
                (_STATIC_DIR / "idp_auth.py").read_text()
            )
        if context.auth.has_oidc_auth:
            (deps_dir / "claims.py").write_text(
                (_STATIC_DIR / "claims.py").read_text()
            )
        (deps_dir / "pagination.py").write_text(
            runtime_module_source("pagination")
        )
        if any(getattr(provider, "dpop", False) for provider in context.auth.providers.values()):
            (deps_dir / "dpop.py").write_text(runtime_module_source("dpop"))
        if any(context.repository_operations.values()):
            (deps_dir / "bindings.py").write_text(
                (_STATIC_DIR / "bindings.py").read_text()
            )

        init_imports: list[str] = []
        auth_files = []
        if context.auth.enabled:
            auth_files += [
                ("auth.py.jinja", "auth.py"),
                ("authorization.py.jinja", "authorization.py"),
            ]
            init_imports.append(
                "from .auth import resolve_principal, get_optional_principal, require_principal"
            )
            init_imports.append("from .authorization import _principal_has_role")
        if context.auth.uses_jwt:
            auth_files.append(("jwt_utils.py.jinja", "jwt_utils.py"))
            init_imports.append("from .jwt_utils import create_jwt_token, decode_jwt_token")
            auth_files.append(("session_tokens.py.jinja", "session_tokens.py"))
            init_imports.append("from .session_tokens import issue_session")
        if context.session.refresh:
            init_imports.append(
                "from .session_tokens import revoke_session, rotate_session"
            )
        if context.session.uses_cookie:
            auth_files.append(("session_cookie.py.jinja", "session_cookie.py"))
            init_imports.append(
                "from .session_cookie import csrf_valid, set_session_cookies, clear_session_cookies"
            )

        for template_name, filename in auth_files:
            (deps_dir / filename).write_text(
                env.get_template(template_name).render(ctx=context, auth=context.auth)
            )

        collections = [
            {
                "name": col_name,
                "class_name": to_pascal_case(col_name),
                "is_sql": context.collection_datastore_type(col_name) in ("postgres", "postgresql"),
            }
            for col_name in context.collections
        ]

        # Deduplicate services by their backing repository: two services that
        # resolve to the same repository share one provider callable.
        seen_repos: set[str] = set()
        service_bindings: list[dict] = []
        for ir_svc in context.services.values():
            repo = ir_svc.repository
            if repo is None or repo in seen_repos:
                continue
            seen_repos.add(repo)
            service_bindings.append({
                "name": repo,
                "class_name": to_pascal_case(repo),
                "is_sql": context.collection_datastore_type(repo) in ("postgres", "postgresql"),
            })

        (deps_dir / "repositories.py").write_text(
            env.get_template("dependencies_repositories.py.jinja").render(
                collections=collections,
                uses_sql=uses_sql,
                uses_mongo=uses_mongo,
            )
        )
        (deps_dir / "services.py").write_text(
            env.get_template("dependencies_services.py.jinja").render(
                collections=service_bindings,
                auth_enabled=context.auth.enabled,
            )
        )

        (deps_dir / "__init__.py").write_text(
            "\n".join(init_imports) + "\n" if init_imports else ""
        )
