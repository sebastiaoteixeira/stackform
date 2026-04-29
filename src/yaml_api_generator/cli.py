import json
import sys

import click


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
    from .compiler.compiler import compile_api
    from .parsing.parser import ConfigErrors

    try:
        compile_api(
            yaml_file=yaml_file,
            schema_file=schema_file,
            output_dir=output_dir,
            target=target,
        )
    except ConfigErrors as error:
        payload = [item.to_dict() for item in error.errors]
        sys.stderr.write(json.dumps(payload, indent=2) + "\n")
        raise SystemExit(1)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"Error: {error}\n")
        raise SystemExit(1)

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

    from .parsing.parser import ConfigErrors
    from .runtime.server import build_app, build_raw_app

    try:
        app = (
            build_raw_app(yaml_file, schema_file)
            if raw
            else build_app(yaml_file, schema_file)
        )
    except ConfigErrors as error:
        payload = [item.to_dict() for item in error.errors]
        sys.stderr.write(json.dumps(payload, indent=2) + "\n")
        raise SystemExit(1)
    except OSError as error:
        payload = [{"code": "FILE_ERROR", "message": str(error), "path": "$"}]
        sys.stderr.write(json.dumps(payload, indent=2) + "\n")
        raise SystemExit(1)

    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option("--host", required=True, help="Target server hostname or IP.")
@click.option("--user", default="ubuntu", help="SSH user (default: ubuntu).")
@click.option("--key", default="~/.ssh/id_rsa", help="Path to SSH private key.")
@click.option(
    "--output",
    "output_dir",
    default="./deploy",
    help="Output directory (default: ./deploy).",
)
@click.option(
    "--schema",
    "schema_file",
    default=None,
    type=click.Path(exists=True),
    help="Path to JSON schema file (auto-detected from spec version if omitted).",
)
def deploy(yaml_file: str, host: str, user: str, key: str, output_dir: str, schema_file: str | None) -> None:
    """Generate Ansible deployment artifacts from a YAML API spec."""
    import sys

    from .deploy.deployer import deploy_api
    from .parsing.parser import ConfigErrors

    try:
        deploy_api(
            yaml_file=yaml_file,
            schema_file=schema_file,
            host=host,
            ssh_user=user,
            ssh_key=key,
            output_dir=output_dir,
        )
    except (ConfigErrors, ValueError, OSError) as error:
        sys.stderr.write(f"Error: {error}\n")
        raise SystemExit(1)

    click.echo(f"Generated deploy artifacts in {output_dir}")

@click.option(
    "--output",
    "output_dir",
    default=None,
    help="Override output directory from ui.frontend.output.",
)
def frontend(yaml_file: str, schema_file: str | None, output_dir: str | None):
    """Generate frontend from a YAML API spec."""
    from .frontend.pipeline import generate_frontend
    from .parsing.parser import ConfigErrors

    try:
        from .parsing.parser import load_and_generate_ir

        result = load_and_generate_ir(yaml_file, schema_file)
        if result.ui_block is None:
            click.echo("Error: No 'ui' block found in the YAML spec.", err=True)
            raise SystemExit(1)

        generate_frontend(
            ir=result.ir,
            ui_block=result.ui_block,
            output_override=output_dir,
        )
    except ConfigErrors as error:
        import json
        import sys

        payload = [item.to_dict() for item in error.errors]
        sys.stderr.write(json.dumps(payload, indent=2) + "\n")
        raise SystemExit(1)
    except (FileNotFoundError, ValueError) as error:
        click.echo(f"Error: {error}", err=True)
        raise SystemExit(1)
