"""CLI commands for YAML API Generator."""

import click

from .utils.error_handler import handle_config_errors, handle_generic_error


@click.group()
def cli():
    """YAML-driven REST API generator."""


@cli.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.argument("what", default="all", type=click.Choice(["all", "backend", "frontend", "deploy"]))
@click.option("-s", "--schema", "schema_file", type=click.Path(exists=True), help="JSON schema file")
@click.option(
    "-o", "--output", "output_dir",
    help="Output directory (default: ./target, or ui.frontend.output/./frontend for frontend-only)",
)
@click.option("-t", "--target", default="fastapi", help="Backend target: fastapi, drf, raw")
@click.option("--json", "output_json", is_flag=True, help="Output errors in JSON")
def build(yaml_file: str, what: str, schema_file: str | None, output_dir: str | None, target: str, output_json: bool):
    """Build backend, frontend, deploy, or all."""
    from pathlib import Path
    from .compiler import compile_project
    from ..parsers.yaml_parser import ConfigErrors, load_and_generate_ir
    from ..generators.frontend.generator import generate_frontend
    from ..generators.frontend.packs.loader import load_pack
    from ..parsers.ui_parser import build_generator_context
    from ..generators.deploy.generate import generate_deploy

    try:
        result = load_and_generate_ir(yaml_file, schema_file)
        artifact_output = output_dir or "./target"

        for w in result.warnings:
            click.echo(f"WARN {w.code} {w.path}: {w.message}", err=True)

        if what in ("all", "backend"):
            compile_project(
                yaml_file=yaml_file,
                schema_file=schema_file,
                output_dir=artifact_output,
                target=target,
            )
            click.echo(f"Backend generated in {artifact_output}")

        if what in ("all", "frontend"):
            if result.ui_block is None:
                if what == "frontend":
                    click.echo("Error: No 'ui' block found in the YAML spec.", err=True)
                    raise SystemExit(1)
            else:
                frontend_block = result.ui_block.get("frontend", {}) or {}
                pack_name = frontend_block.get("pack")

                if isinstance(pack_name, str) and pack_name.strip():
                    overwrite = frontend_block.get("overwrite", "never")
                    pack = load_pack(pack_name)
                    ui = build_generator_context(result.ir, result.ui_block, pack.manifest)

                    frontend_output = (
                        f"{artifact_output}/frontend"
                        if what == "all"
                        else output_dir or frontend_block.get("output") or "./frontend"
                    )

                    generate_frontend(
                        ir=result.ir,
                        ui=ui,
                        pack_name=pack_name,
                        output_override=frontend_output,
                        overwrite=overwrite,
                    )
                    click.echo("Frontend generated")
                elif what == "frontend":
                    click.echo("Error: ui.frontend.pack is required.", err=True)
                    raise SystemExit(1)

        if what in ("all", "deploy"):
            if result.ir.deploy is None:
                if what == "deploy":
                    click.echo("Error: No 'deploy' block found in the YAML spec.", err=True)
                    raise SystemExit(1)
            else:
                generate_deploy(
                    ir=result.ir,
                    host="localhost",
                    ssh_user="ubuntu",
                    ssh_key="~/.ssh/id_rsa",
                    output_dir=artifact_output,
                    spec_dir=Path(yaml_file).parent,
                )
                click.echo(f"Deploy artifacts generated in {artifact_output}")

    except ConfigErrors as error:
        handle_config_errors(error, yaml_file, "json" if output_json else "human")
    except (OSError, ValueError, FileNotFoundError) as error:
        handle_generic_error(error)


@cli.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option("-s", "--schema", "schema_file", type=click.Path(exists=True), help="JSON schema file")
@click.option("--host", default="127.0.0.1", help="Host to bind")
@click.option("-p", "--port", default=8000, type=int, help="Port to bind")
@click.option("--raw", is_flag=True, help="Use raw ASGI runner")
@click.option("-r", "--reload", is_flag=True, help="Reload the app when the spec changes")
@click.option("--json", "output_json", is_flag=True, help="Output errors in JSON")
def run(yaml_file: str, schema_file: str | None, host: str, port: int, raw: bool, reload: bool, output_json: bool):
    """Run development server."""
    import uvicorn

    from ..parsers.yaml_parser import ConfigErrors
    from ..server import build_app, build_raw_app
    from ..server.factory import RAW_ENV, SCHEMA_ENV, SPEC_ENV

    if reload:
        import os
        from pathlib import Path

        os.environ[SPEC_ENV] = yaml_file
        os.environ[RAW_ENV] = "1" if raw else "0"
        if schema_file:
            os.environ[SCHEMA_ENV] = schema_file
        uvicorn.run(
            "yaml_api_generator.server.factory:create_app",
            factory=True,
            reload=True,
            reload_dirs=[str(Path(yaml_file).parent)],
            reload_includes=["*.yaml", "*.yml"],
            host=host,
            port=port,
        )
        return

    try:
        app = (
            build_raw_app(yaml_file, schema_file)
            if raw
            else build_app(yaml_file, schema_file)
        )
    except ConfigErrors as error:
        handle_config_errors(error, yaml_file, "json" if output_json else "human")
    except OSError as error:
        handle_generic_error(error)

    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.argument("pack_dir", type=click.Path(exists=True))
@click.option("-o", "--output", "output_file", help="Output file path")
def pack(pack_dir: str, output_file: str | None):
    """Package a UI pack for distribution."""
    import tarfile
    from pathlib import Path
    import yaml

    pack_path = Path(pack_dir)
    manifest_path = pack_path / "pack.yaml"

    if not manifest_path.is_file():
        click.echo(f"Error: pack.yaml not found in {pack_dir}", err=True)
        raise SystemExit(1)

    with manifest_path.open("r") as f:
        manifest = yaml.safe_load(f)

    pack_name = manifest.get("name")
    if not pack_name:
        click.echo("Error: pack.yaml must have a 'name' field", err=True)
        raise SystemExit(1)

    pack_version = manifest.get("version", "0.0.0")
    default_output = f"{pack_name}-{pack_version}.tar.gz"
    output_path = Path(output_file or default_output)

    with tarfile.open(output_path, "w:gz") as tar:
        tar.add(pack_path, arcname=pack_name)

    click.echo(f"Packed {pack_dir} to {output_path}")


@cli.command()
@click.argument("pack_path", type=click.Path(exists=True))
def install_pack(pack_path: str):
    """Install a UI pack."""
    import tarfile
    from pathlib import Path

    pack_file = Path(pack_path)
    packs_dir = Path.home() / ".yaml-api-generator" / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)

    if not pack_file.suffix == ".gz" and not pack_file.name.endswith(".tar.gz"):
        click.echo(f"Error: Expected .tar.gz file, got {pack_file}", err=True)
        raise SystemExit(1)

    with tarfile.open(pack_file, "r:gz") as tar:
        members = tar.getmembers()
        if not members:
            click.echo("Error: Pack archive is empty", err=True)
            raise SystemExit(1)

        root_name = members[0].name.split("/")[0]
        target_dir = packs_dir / root_name

        if target_dir.exists():
            click.echo(f"Pack '{root_name}' already installed. Remove {target_dir} first.", err=True)
            raise SystemExit(1)

        tar.extractall(packs_dir)

    click.echo(f"Installed pack '{root_name}' to {target_dir}")


@cli.command()
def list_packs():
    """List installed UI packs."""
    from pathlib import Path
    import yaml

    builtin_packs_dir = Path(__file__).parent.parent / "generators" / "frontend" / "packs" / "builtin"
    user_packs_dir = Path.home() / ".yaml-api-generator" / "packs"

    packs = []

    if builtin_packs_dir.exists():
        for pack_dir in builtin_packs_dir.iterdir():
            if pack_dir.is_dir() and (pack_dir / "pack.yaml").exists():
                with (pack_dir / "pack.yaml").open("r") as f:
                    manifest = yaml.safe_load(f)
                packs.append({
                    "name": manifest.get("name", pack_dir.name),
                    "version": manifest.get("version", "unknown"),
                    "location": "built-in",
                    "path": str(pack_dir),
                })

    if user_packs_dir.exists():
        for pack_dir in user_packs_dir.iterdir():
            if pack_dir.is_dir() and (pack_dir / "pack.yaml").exists():
                with (pack_dir / "pack.yaml").open("r") as f:
                    manifest = yaml.safe_load(f)
                packs.append({
                    "name": manifest.get("name", pack_dir.name),
                    "version": manifest.get("version", "unknown"),
                    "location": "user",
                    "path": str(pack_dir),
                })

    if not packs:
        click.echo("No packs installed")
        return

    click.echo(f"{'NAME':<20} {'VERSION':<12} {'LOCATION':<12} PATH")
    click.echo("-" * 80)
    for pack in packs:
        click.echo(f"{pack['name']:<20} {pack['version']:<12} {pack['location']:<12} {pack['path']}")


@cli.command()
@click.argument("pack_name")
def remove_pack(pack_name: str):
    """Remove an installed UI pack."""
    import shutil
    from pathlib import Path
    import yaml

    builtin_packs_dir = Path(__file__).parent.parent / "generators" / "frontend" / "packs" / "builtin"
    user_packs_dir = Path.home() / ".yaml-api-generator" / "packs"

    builtin_pack = builtin_packs_dir / pack_name if builtin_packs_dir.exists() else None
    if builtin_pack and builtin_pack.exists():
        click.echo(f"Error: Cannot remove built-in pack '{pack_name}'", err=True)
        raise SystemExit(1)

    user_pack = user_packs_dir / pack_name
    if not user_pack.exists():
        click.echo(f"Error: Pack '{pack_name}' not found", err=True)
        raise SystemExit(1)

    if not (user_pack / "pack.yaml").exists():
        click.echo(f"Error: '{pack_name}' is not a valid pack directory", err=True)
        raise SystemExit(1)

    shutil.rmtree(user_pack)
    click.echo(f"Removed pack '{pack_name}'")


@cli.group()
def migrate():
    """Manage database migrations (relational via Alembic, MongoDB native)."""


_spec_arg = click.argument("yaml_file", type=click.Path(exists=True))
_datastore_opt = click.option("--datastore", default=None, help="Datastore name")


@migrate.command("new")
@_spec_arg
@click.option("-m", "--message", default="auto", help="Revision message")
@_datastore_opt
def migrate_new(yaml_file: str, message: str, datastore: str | None):
    """Autogenerate a revision from the spec (scaffolds on first run)."""
    from ..migrations.dispatch import resolve_driver

    driver, config = resolve_driver(yaml_file, datastore)
    driver.new_revision(config, message)


@migrate.command("up")
@_spec_arg
@click.option(
    "--to", "target", default="head", help="Revision id, +N, or head (default head)"
)
@_datastore_opt
def migrate_up(yaml_file: str, target: str, datastore: str | None):
    """Apply migrations forward."""
    from ..migrations.dispatch import resolve_driver

    driver, config = resolve_driver(yaml_file, datastore)
    driver.upgrade(config, target)


@migrate.command("down")
@_spec_arg
@click.option(
    "--to", "target", default="-1", help="Revision id, -N, or base (default -1)"
)
@_datastore_opt
def migrate_down(yaml_file: str, target: str, datastore: str | None):
    """Revert migrations."""
    from ..migrations.dispatch import resolve_driver

    driver, config = resolve_driver(yaml_file, datastore)
    driver.downgrade(config, target)


@migrate.command("status")
@_spec_arg
@_datastore_opt
def migrate_status(yaml_file: str, datastore: str | None):
    """Show the current revision."""
    from ..migrations.dispatch import resolve_driver

    driver, config = resolve_driver(yaml_file, datastore)
    driver.status(config)


@migrate.command("history")
@_spec_arg
@_datastore_opt
def migrate_history(yaml_file: str, datastore: str | None):
    """List revisions."""
    from ..migrations.dispatch import resolve_driver

    driver, config = resolve_driver(yaml_file, datastore)
    driver.history(config)
