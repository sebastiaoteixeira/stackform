"""CLI commands for YAML API Generator.

Provides four main commands:
- compile: Generate backend code from YAML spec
- dev: Run development server with hot-reload
- frontend: Generate frontend code with UI packs
- deploy: Generate deployment artifacts (Docker, systemd)
"""

import click

from .utils.error_handler import handle_config_errors, handle_generic_error


@click.group()
def cli():
    """YAML-driven REST API generator."""


@cli.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option(
    "--schema",
    "schema_file",
    default=None,
    type=click.Path(exists=True),
    help="Path to JSON schema file (auto-detected from spec version if omitted).",
)
@click.option(
    "--output",
    "output_dir",
    default="./target",
    help="Output directory (default: ./target).",
)
@click.option(
    "--target",
    default="fastapi",
    help="Code generator backend (default: fastapi).",
)
def compile(yaml_file: str, schema_file: str | None, output_dir: str, target: str):
    """Compile a YAML API spec into source code."""
    from .compiler import compile_project
    from ..parsers.yaml_parser import ConfigErrors

    try:
        compile_project(
            yaml_file=yaml_file,
            schema_file=schema_file,
            output_dir=output_dir,
            target=target,
        )
    except ConfigErrors as error:
        handle_config_errors(error)
    except (OSError, ValueError) as error:
        handle_generic_error(error)

    click.echo(f"Generated {target} project in {output_dir}")


@cli.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option(
    "--schema",
    "schema_file",
    default=None,
    type=click.Path(exists=True),
    help="Path to JSON schema file (auto-detected from spec version if omitted).",
)
@click.option("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1).")
@click.option("--port", default=8000, type=int, help="Port to bind (default: 8000).")
@click.option("--raw", is_flag=True, default=False, help="Use raw ASGI runner (no FastAPI).")
def dev(yaml_file: str, schema_file: str | None, host: str, port: int, raw: bool):
    """Run the YAML API development server."""
    import uvicorn

    from ..parsers.yaml_parser import ConfigErrors
    from ..server import build_app, build_raw_app

    try:
        app = (
            build_raw_app(yaml_file, schema_file)
            if raw
            else build_app(yaml_file, schema_file)
        )
    except ConfigErrors as error:
        handle_config_errors(error)
    except OSError as error:
        handle_generic_error(error)

    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option(
    "--schema",
    "schema_file",
    default=None,
    type=click.Path(exists=True),
    help="Path to JSON schema file (auto-detected from spec version if omitted).",
)
@click.option(
    "--output",
    "output_dir",
    default=None,
    help="Override output directory from ui.frontend.output.",
)
def frontend(yaml_file: str, schema_file: str | None, output_dir: str | None):
    """Generate frontend from a YAML API spec."""
    from ..parsers.yaml_parser import ConfigErrors, load_and_generate_ir
    from ..generators.frontend.generator import generate_frontend
    from ..generators.frontend.packs.loader import load_pack
    from .parsers.ui_parser import build_generator_context

    try:
        result = load_and_generate_ir(yaml_file, schema_file)
        if result.ui_block is None:
            click.echo("Error: No 'ui' block found in the YAML spec.", err=True)
            raise SystemExit(1)

        frontend_block = result.ui_block.get("frontend", {}) or {}
        pack_name = frontend_block.get("pack")
        if not isinstance(pack_name, str) or not pack_name.strip():
            click.echo("Error: ui.frontend.pack is required.", err=True)
            raise SystemExit(1)

        overwrite = frontend_block.get("overwrite", "never")
        pack = load_pack(pack_name)
        ui = build_generator_context(result.ir, result.ui_block, pack.manifest)

        generate_frontend(
            ir=result.ir,
            ui=ui,
            pack_name=pack_name,
            output_override=output_dir,
            overwrite=overwrite,
        )
    except ConfigErrors as error:
        handle_config_errors(error)
    except (FileNotFoundError, ValueError) as error:
        handle_generic_error(error)


@cli.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option(
    "--schema",
    "schema_file",
    default=None,
    type=click.Path(exists=True),
    help="Path to JSON schema file (auto-detected from spec version if omitted).",
)
@click.option("--host", required=True, help="Target server hostname or IP.")
@click.option("--user", default="ubuntu", help="SSH user (default: ubuntu).")
@click.option("--key", default="~/.ssh/id_rsa", help="Path to SSH private key.")
@click.option(
    "--output",
    "output_dir",
    default="./deploy",
    help="Output directory (default: ./deploy).",
)
def deploy(yaml_file: str, schema_file: str | None, host: str, user: str, key: str, output_dir: str) -> None:
    """Generate deployment artifacts from a YAML API spec."""
    from pathlib import Path

    from ..parsers.yaml_parser import ConfigErrors, load_and_generate_ir
    from ..generators.deploy.generate import generate_deploy

    try:
        raw_text = Path(yaml_file).read_text()
        result = load_and_generate_ir(yaml_file, schema_file)
        generate_deploy(
            ir=result.ir,
            raw_yaml_text=raw_text,
            host=host,
            ssh_user=user,
            ssh_key=key,
            output_dir=output_dir,
        )
    except ConfigErrors as error:
        handle_config_errors(error)
    except (ValueError, OSError) as error:
        handle_generic_error(error)

    click.echo(f"Generated deploy artifacts in {output_dir}")
