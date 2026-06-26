from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..base import DeployGenerator
from ..context import DeployContext, SystemdDeployContext

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class SystemdDeployGenerator(DeployGenerator):
    def generate(self, ctx: DeployContext, output_dir: Path, spec_dir: Path) -> None:
        assert isinstance(ctx, SystemdDeployContext)
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        always = [
            ("inventory.yml.jinja", "inventory.yml"),
            ("playbook.yml.jinja", "playbook.yml"),
            ("env.example.jinja", ".env.example"),
        ]
        for tmpl, out in always:
            self._render(env, tmpl, ctx, output_dir / out)

        files_dir = output_dir / "files"
        files_dir.mkdir(exist_ok=True)
        self._render(env, "files/app.service.jinja", ctx, files_dir / "app.service")

        roles_app = output_dir / "roles" / "app" / "tasks"
        roles_app.mkdir(parents=True, exist_ok=True)
        self._render(env, "roles/app/tasks/main.yml.jinja", ctx, roles_app / "main.yml")

        roles_py = output_dir / "roles" / "python" / "tasks"
        roles_py.mkdir(parents=True, exist_ok=True)
        self._render(env, "roles/python/tasks/main.yml.jinja", ctx, roles_py / "main.yml")

        if ctx.mongo_local:
            roles_mongo = output_dir / "roles" / "mongodb" / "tasks"
            roles_mongo.mkdir(parents=True, exist_ok=True)
            self._render(env, "roles/mongodb/tasks/main.yml.jinja", ctx, roles_mongo / "main.yml")

    def _render(self, env: Environment, tmpl: str, ctx: DeployContext, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(env.get_template(tmpl).render(ctx=ctx))