from dataclasses import replace
from pathlib import Path

from ..base import DeployGenerator, Ignore
from ..context import DockerDeployContext
from ..staging import BundleStager

_BUNDLE_FILES = (
    ("docker-compose.yml.jinja", "docker-compose.yml"),
    ("Dockerfile.jinja", "backend/Dockerfile"),
    ("README.md.jinja", "README.md"),
)

# The nginx templates are rendered from the environment each time the frontend container starts.
_FRONTEND_FILES = (
    ("Dockerfile.frontend.jinja", "frontend/Dockerfile"),
    ("nginx/default.conf.template.jinja", "nginx/default.conf.template"),
    ("nginx/config.js.template.jinja", "nginx/config.js.template"),
)


class DockerDeployGenerator(DeployGenerator[DockerDeployContext]):
    runtime_dir = Path(__file__).parent

    def stage(self, ctx: DockerDeployContext, stager: BundleStager) -> DockerDeployContext:
        stager.packages(ctx.packages)
        stager.frontend(ctx.frontend)
        return replace(ctx, extra_services=stager.services(ctx.extra_services))

    def files(self, ctx: DockerDeployContext) -> tuple[tuple[str, str], ...]:
        return (*_BUNDLE_FILES, *(_FRONTEND_FILES if ctx.frontend else ()))

    def ignore(self, ctx: DockerDeployContext) -> Ignore:
        """Only the delivery the bundle uses is shipped."""
        return lambda directory, names: [
            name for name in names if Path(directory).name == "deliver" and name != f"{ctx.delivery}.yml"
        ]
