from abc import ABC, abstractmethod
from pathlib import Path

from .context import DeployContext


class DeployGenerator(ABC):
    @abstractmethod
    def generate(self, ctx: DeployContext, output_dir: Path, spec_dir: Path) -> None: ...
