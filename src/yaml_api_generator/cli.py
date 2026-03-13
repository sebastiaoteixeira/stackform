import json
import sys
from importlib.resources import as_file, files
from pathlib import Path

import click


def _default_schema_path() -> Path:
    schema_resource = files("yaml_api_generator.schemas").joinpath(
        "yaml-spec-v0.1.schema.json"
    )
    with as_file(schema_resource) as schema_path:
        return schema_path


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
    help="Path to JSON schema file.",
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
    from .parser import ConfigErrors

    schema = schema_file or str(_default_schema_path())

    try:
        compile_api(
            yaml_file=yaml_file,
            schema_file=schema,
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
    help="Path to JSON schema file.",
)
@click.option("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1).")
@click.option("--port", default=8000, type=int, help="Port to bind (default: 8000).")
@click.option("--raw", is_flag=True, default=False, help="Use raw ASGI runner (no FastAPI).")
def dev(yaml_file: str, schema_file: str | None, host: str, port: int, raw: bool):
    """Run the YAML API development server."""
    import uvicorn

    from .parser import ConfigErrors
    from .server import build_app, build_raw_app

    schema = schema_file or str(_default_schema_path())

    try:
        app = build_raw_app(yaml_file, schema) if raw else build_app(yaml_file, schema)
    except ConfigErrors as error:
        payload = [item.to_dict() for item in error.errors]
        sys.stderr.write(json.dumps(payload, indent=2) + "\n")
        raise SystemExit(1)
    except OSError as error:
        payload = [{"code": "FILE_ERROR", "message": str(error), "path": "$"}]
        sys.stderr.write(json.dumps(payload, indent=2) + "\n")
        raise SystemExit(1)

    uvicorn.run(app, host=host, port=port)
