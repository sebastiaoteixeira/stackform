from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, ClassVar

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

from yaml_api_generator.generators.backend.compile_context import CompileContext
from yaml_api_generator.generators.backend.runtime_literals import py_constructor
from yaml_api_generator.utils.strings import to_pascal_case

from .utils import runtime_module_source


@dataclass
class RenderConfig:
    """Configuration for collection-based rendering."""

    template_name: str
    output_subdir: str
    import_class_suffix: str | None = None
    import_pattern: str | None = None
    output_filename_pattern: str = "{col_name}.py"
    context_builder: Callable[[str, dict, CompileContext], dict] | None = None
    should_render: Callable[[str, dict, CompileContext], bool] | None = None
    additional_files: list[tuple[str, str]] = field(default_factory=list)
    generate_init_imports: bool = True


@dataclass
class SingleFileRenderConfig:
    """Configuration for single-file rendering."""

    template_name: str
    output_path: str | Path
    context_builder: Callable[[CompileContext], dict] | None = None


def template_environment(*template_dirs: Path) -> Environment:
    """Build the Jinja environment every backend generator renders through.

    StrictUndefined is what keeps a missing context key from reaching the
    emitted source: the default undefined renders through repr() as the bare
    token Undefined, which is valid Python syntax and therefore survives every
    syntax-level check the generated project is put through.
    """
    env = Environment(
        loader=ChoiceLoader([FileSystemLoader(str(d)) for d in template_dirs]),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    env.filters["py_constructor"] = py_constructor
    return env


class CodeGenerator(ABC):
    asgi_application: ClassVar[str] = "app:app"
    """Import path an ASGI server loads to serve the generated backend."""

    @abstractmethod
    def generate(self, context: CompileContext, output_dir: Path) -> None: ...


class TemplateBasedGenerator(CodeGenerator):
    """Base class providing template rendering utilities for backend generators."""

    def __init__(self):
        self._dir_prefix: str = ""

    @property
    def dir_prefix(self) -> str:
        """Directory prefix for all generated code (e.g., 'api' for DRF)."""
        return self._dir_prefix

    def _render_collection_based(
        self,
        env: Environment,
        context: CompileContext,
        collections_by_name: dict[str, dict],
        output_dir: Path,
        config: RenderConfig,
    ) -> None:
        """Render templates for each collection with automatic __init__.py generation."""
        target_dir = output_dir
        if self.dir_prefix:
            target_dir = target_dir / self.dir_prefix
        target_dir = target_dir / config.output_subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        for template_name, filename in config.additional_files:
            template = env.get_template(template_name)
            content = template.render(ctx=context)
            (target_dir / filename).write_text(content)

        template = env.get_template(config.template_name)
        init_imports: list[str] = []

        for col_name, col_data in collections_by_name.items():
            if config.should_render and not config.should_render(col_name, col_data, context):
                continue

            if config.context_builder:
                template_context = config.context_builder(col_name, col_data, context)
            else:
                template_context = {
                    "collection_name": col_name,
                    "ctx": context,
                }

            content = template.render(**template_context)

            filename = config.output_filename_pattern.format(col_name=col_name)
            (target_dir / filename).write_text(content)

            if config.generate_init_imports:
                import_stmt = self._generate_import_statement(col_name, col_data, config)
                if import_stmt:
                    init_imports.append(import_stmt)

        init_content = "\n".join(init_imports) + "\n" if init_imports else ""
        (target_dir / "__init__.py").write_text(init_content)

    def _generate_import_statement(
        self,
        col_name: str,
        col_data: dict,
        config: RenderConfig,
    ) -> str | None:
        """Generate import statement for __init__.py."""
        if config.import_pattern:
            class_name = to_pascal_case(col_name)
            return config.import_pattern.format(
                col_name=col_name,
                class_name=class_name,
            )
        elif config.import_class_suffix:
            class_name = to_pascal_case(col_name)
            full_class_name = f"{class_name}{config.import_class_suffix}"
            return f"from .{col_name} import {full_class_name}"
        else:
            models = col_data.get("models", [])
            if models:
                class_names = [m.name for m in models]
                return f"from .{col_name} import {', '.join(class_names)}"
            return None

    @staticmethod
    def _render_service_inputs(env: Environment, output_dir: Path, package: str) -> None:
        """Write the field validator and the service-input helper built on it into ``package``."""
        package_dir = output_dir / package
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "fields.py").write_text(runtime_module_source("fields"))
        (package_dir / "service_inputs.py").write_text(
            env.get_template("service_inputs.py.jinja").render(
                fields_module=f"{package}.fields" if package else "fields"
            )
        )

    def _render_single_file(
        self,
        env: Environment,
        context: CompileContext,
        output_dir: Path,
        config: SingleFileRenderConfig,
    ) -> None:
        """Render a single template to a single file."""
        template = env.get_template(config.template_name)

        if config.context_builder:
            template_context = config.context_builder(context)
        else:
            template_context = {"ctx": context}

        content = template.render(**template_context)

        output_path = output_dir / config.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

    def _render_directory(
        self,
        env: Environment,
        context: CompileContext,
        output_dir: Path,
        subdir: str,
        files: list[tuple[str, str]],
        init_imports: list[str] | None = None,
    ) -> None:
        """Render multiple files into a directory with optional __init__.py."""
        target_dir = output_dir
        if self.dir_prefix:
            target_dir = target_dir / self.dir_prefix
        target_dir = target_dir / subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        for template_name, filename in files:
            template = env.get_template(template_name)
            content = template.render(ctx=context, auth=context.auth)
            (target_dir / filename).write_text(content)

        if init_imports is not None:
            init_content = "\n".join(init_imports) + "\n"
            (target_dir / "__init__.py").write_text(init_content)
