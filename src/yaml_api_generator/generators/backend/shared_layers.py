"""The service and repository layers a backend renders from the shared templates."""

from pathlib import Path

from jinja2 import Environment

from .base import RenderConfig, TemplateBasedGenerator
from .compile_context import CompileContext
from .inheritance import (
    own_repository_operations,
    own_service_operations,
    repository_base_class,
    route_operations,
    service_base_class,
)
from .utils import identity_service_context


class SharedLayersGenerator(TemplateBasedGenerator):
    """A generator whose services and repositories, abstract bases included, come from the shared templates."""

    auth_module: str
    """Module of the generated app that provides ``hash_password``."""

    @property
    def module_prefix(self) -> str:
        return f"{self.dir_prefix}." if self.dir_prefix else ""

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
                context_builder=self._service_context,
                additional_files=[("exceptions.py.jinja", "exceptions.py")],
            )
        )
        template = env.get_template("service_base.py.jinja")
        for base in context.service_bases.values():
            parent = context.service_bases.get(base.inherits)
            (output_dir / self.dir_prefix / "services" / f"{base.name}.py").write_text(template.render(
                collection_name=base.name,
                module_prefix=self.module_prefix,
                custom_operations=own_service_operations(base.operations, parent),
                generated_base=service_base_class(parent),
            ))

    def _service_context(self, col_name: str, col_data: dict, context: CompileContext) -> dict:
        base = context.service_base(col_name)
        return {
            "collection_name": col_name,
            "is_async": True,
            **identity_service_context(context, col_name),
            "module_prefix": self.module_prefix,
            "auth_module": self.auth_module,
            "custom_operations": own_service_operations(route_operations(col_data), base),
            "generated_base": service_base_class(base),
        }

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
                    "custom_operations": own_repository_operations(ctx, col_name),
                    "generated_base": repository_base_class(ctx, col_name),
                    "module_prefix": self.module_prefix,
                },
            )
        )
        template = env.get_template("repository_base.py.jinja")
        for base_name in context.repository_abstract:
            (output_dir / self.dir_prefix / "repositories" / f"{base_name}.py").write_text(template.render(
                collection_name=base_name,
                custom_operations=own_repository_operations(context, base_name),
                generated_base=repository_base_class(context, base_name),
            ))
