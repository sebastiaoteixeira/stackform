import shutil
from dataclasses import replace
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from ..base import DeployGenerator
from ..context import DeployContext, DockerDeployContext

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class DockerDeployGenerator(DeployGenerator):
    def generate(self, ctx: DeployContext, output_dir: Path, spec_dir: Path) -> None:
        assert isinstance(ctx, DockerDeployContext)
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        env.filters["to_yaml"] = lambda v: yaml.dump(
            v, default_flow_style=False, sort_keys=False
        ).rstrip()
        output_dir.mkdir(parents=True, exist_ok=True)
        ctx = replace(
            ctx,
            extra_services=self._stage_build_contexts(ctx.extra_services, spec_dir, output_dir),
        )

        always = [
            ("inventory.yml.jinja", "inventory.yml"),
            ("playbook.yml.jinja", "playbook.yml"),
            ("docker-compose.yml.jinja", "docker-compose.yml"),
            ("Dockerfile.jinja", "backend/Dockerfile"),
            ("env.example.jinja", ".env.example"),
            ("README.md.jinja", "README.md"),
        ]
        for tmpl, out in always:
            self._render(env, tmpl, ctx, output_dir / out)

        if ctx.has_frontend:
            self._render(env, "nginx.conf.jinja", ctx, output_dir / "nginx.conf")
            self._render(env, "Dockerfile.frontend.jinja", ctx, output_dir / "frontend" / "Dockerfile")

        roles_app_tasks = output_dir / "roles" / "app" / "tasks"
        roles_app_tasks.mkdir(parents=True, exist_ok=True)
        self._render(env, "roles/app/tasks/main.yml.jinja", ctx, roles_app_tasks / "main.yml")

        roles_app_templates = output_dir / "roles" / "app" / "templates"
        roles_app_templates.mkdir(parents=True, exist_ok=True)
        self._render(env, "roles/app/templates/env.j2.jinja", ctx, roles_app_templates / "env.j2")

        if ctx.mongo_local:
            roles_mongodb_tasks = output_dir / "roles" / "mongodb" / "tasks"
            roles_mongodb_tasks.mkdir(parents=True, exist_ok=True)
            self._render(env, "roles/mongodb/tasks/main.yml.jinja", ctx, roles_mongodb_tasks / "main.yml")

    def _stage_build_contexts(
        self,
        services: tuple[tuple[str, dict], ...],
        spec_dir: Path,
        output_dir: Path,
    ) -> tuple[tuple[str, dict], ...]:
        """Copy each service's build context into the bundle so it is self-contained.

        A `build:` path (string or `build.context`) is resolved relative to the
        spec, copied into the output directory, and rewritten to a bundle-relative
        path so `docker compose up --build` works from the generated bundle alone.
        """
        staged: list[tuple[str, dict]] = []
        for name, config in services:
            build = config.get("build")
            if isinstance(build, str):
                context = build
            elif isinstance(build, dict):
                context = build.get("context")
            else:
                context = None
            if not context:
                staged.append((name, config))
                continue
            source = (spec_dir / context).resolve()
            if not source.is_dir():
                raise ValueError(
                    f"deploy service '{name}' build context not found: {source}"
                )
            if any(p.resolve().is_relative_to(source) for p in (spec_dir, output_dir)):
                raise ValueError(
                    f"deploy service '{name}' build context must be a subdirectory "
                    f"of the spec that excludes the output: {source}"
                )
            shutil.copytree(source, output_dir / source.name, dirs_exist_ok=True)
            local = f"./{source.name}"
            if isinstance(build, str):
                new_build: str | dict = local
            else:
                assert isinstance(build, dict)
                new_build = {**build, "context": local}
            staged.append((name, {**config, "build": new_build}))
        return tuple(staged)

    def _render(self, env: Environment, tmpl: str, ctx: DeployContext, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(env.get_template(tmpl).render(ctx=ctx))