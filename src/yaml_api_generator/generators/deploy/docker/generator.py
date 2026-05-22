from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from ..base import DeployGenerator
from ..context import DeployContext, DockerDeployContext

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class DockerDeployGenerator(DeployGenerator):
    def generate(self, ctx: DeployContext, output_dir: Path) -> None:
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

        env_content = env.get_template("env.example.jinja").render(ctx=ctx)
        (output_dir / ".env").write_text(env_content)

        roles_app = output_dir / "roles" / "app" / "tasks"
        roles_app.mkdir(parents=True, exist_ok=True)
        self._render(env, "roles/app/tasks/main.yml.jinja", ctx, roles_app / "main.yml")

        if ctx.mongo_local:
            roles_mongo = output_dir / "roles" / "mongodb" / "tasks"
            roles_mongo.mkdir(parents=True, exist_ok=True)
            self._render(env, "roles/mongodb/tasks/main.yml.jinja", ctx, roles_mongo / "main.yml")

    def _render(self, env: Environment, tmpl: str, ctx: DeployContext, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(env.get_template(tmpl).render(ctx=ctx))