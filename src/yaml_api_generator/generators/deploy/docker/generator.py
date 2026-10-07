import shutil
from dataclasses import replace
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from ..base import DeployGenerator
from ..context import DeployContext, DockerDeployContext
from ..staging import BundleStager

_TEMPLATES_DIR = Path(__file__).parent / "templates"
# Ansible files that never vary are shipped verbatim; the role reads the bundle's settings from its defaults.
_ANSIBLE_DIR = Path(__file__).parent / "ansible"

_BUNDLE_FILES = (
    ("inventory.yml.jinja", "inventory.yml"),
    ("playbook.yml.jinja", "playbook.yml"),
    ("docker-compose.yml.jinja", "docker-compose.yml"),
    ("Dockerfile.jinja", "backend/Dockerfile"),
    ("env.example.jinja", ".env.example"),
    ("README.md.jinja", "README.md"),
    ("roles/app/defaults/main.yml.jinja", "roles/app/defaults/main.yml"),
)

# The nginx templates are rendered from the environment each time the frontend container starts.
_FRONTEND_FILES = (
    ("Dockerfile.frontend.jinja", "frontend/Dockerfile"),
    ("nginx/default.conf.template.jinja", "nginx/default.conf.template"),
    ("nginx/config.js.template.jinja", "nginx/config.js.template"),
)


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
        stager = BundleStager(spec_dir, output_dir)
        ctx = replace(ctx, extra_services=stager.services(ctx.extra_services))
        stager.packages(ctx.packages)
        stager.frontend(ctx.frontend)

        for tmpl, out in (*_BUNDLE_FILES, *(_FRONTEND_FILES if ctx.frontend else ())):
            self._render(env, tmpl, ctx, output_dir / out)
        for environment in ctx.environments:
            self._render(
                env, "group_vars/environment.yml.jinja", ctx,
                output_dir / "group_vars" / f"{environment.name}.yml", environment=environment,
            )
        if ctx.mongo_local:
            self._render(env, "roles/mongodb/tasks/main.yml.jinja", ctx, output_dir / "roles/mongodb/tasks/main.yml")

        shutil.copytree(_ANSIBLE_DIR, output_dir, dirs_exist_ok=True, ignore=self._other_deliveries(ctx.delivery))

    @staticmethod
    def _other_deliveries(delivery: str):
        return lambda directory, names: [
            name for name in names if Path(directory).name == "deliver" and name != f"{delivery}.yml"
        ]

    def _render(self, env: Environment, tmpl: str, ctx: DeployContext, dest: Path, **variables) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(env.get_template(tmpl).render(ctx=ctx, **variables))