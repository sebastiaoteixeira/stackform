from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ...base import DeployGenerator
from ...deploy_context import DeployContext, DockerDeployContext

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
        output_dir.mkdir(parents=True, exist_ok=True)

        always = [
            ("inventory.yml.j2", "inventory.yml"),
            ("playbook.yml.j2", "playbook.yml"),
            ("docker-compose.yml.j2", "docker-compose.yml"),
            ("Dockerfile.j2", "Dockerfile"),
            ("env.example.j2", ".env.example"),
        ]
        for tmpl, out in always:
            self._render(env, tmpl, ctx, output_dir / out)

        roles_app = output_dir / "roles" / "app" / "tasks"
        roles_app.mkdir(parents=True, exist_ok=True)
        self._render(env, "roles/app/tasks/main.yml.j2", ctx, roles_app / "main.yml")

        if ctx.mongo_local:
            roles_mongo = output_dir / "roles" / "mongodb" / "tasks"
            roles_mongo.mkdir(parents=True, exist_ok=True)
            self._render(env, "roles/mongodb/tasks/main.yml.j2", ctx, roles_mongo / "main.yml")

    def _render(self, env: Environment, tmpl: str, ctx: DeployContext, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(env.get_template(tmpl).render(ctx=ctx))
