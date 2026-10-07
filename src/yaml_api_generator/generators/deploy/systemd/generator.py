from pathlib import Path

from ..base import DeployGenerator
from ..context import SystemdDeployContext
from ..staging import BundleStager


class SystemdDeployGenerator(DeployGenerator[SystemdDeployContext]):
    runtime_dir = Path(__file__).parent
    roles = ("python", "app")

    def stage(self, ctx: SystemdDeployContext, stager: BundleStager) -> SystemdDeployContext:
        stager.packages(ctx.packages)
        return ctx
