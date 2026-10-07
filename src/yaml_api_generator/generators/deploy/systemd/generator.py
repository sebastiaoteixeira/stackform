from pathlib import Path

from ..base import DeployGenerator
from ..context import SystemdDeployContext
from ..staging import BundleStager

_BUNDLE_FILES = (
    ("playbook.yml.jinja", "playbook.yml"),
    ("roles/app/defaults/main.yml.jinja", "roles/app/defaults/main.yml"),
)

_MONGO_FILES = (("roles/mongodb/tasks/main.yml.jinja", "roles/mongodb/tasks/main.yml"),)


class SystemdDeployGenerator(DeployGenerator[SystemdDeployContext]):
    runtime_dir = Path(__file__).parent

    def stage(self, ctx: SystemdDeployContext, stager: BundleStager) -> SystemdDeployContext:
        stager.packages(ctx.packages)
        return ctx

    def files(self, ctx: SystemdDeployContext) -> tuple[tuple[str, str], ...]:
        return (*_BUNDLE_FILES, *(_MONGO_FILES if ctx.mongo_local else ()))
