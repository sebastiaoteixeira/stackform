from abc import ABC, abstractmethod
from pathlib import Path

from yaml_api_generator.generators.backend.compile_context import CompileContext


class CodeGenerator(ABC):
    @abstractmethod
    def generate(self, context: CompileContext, output_dir: Path) -> None: ...
