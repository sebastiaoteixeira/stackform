from abc import ABC, abstractmethod
from pathlib import Path

from ..compile_context import CompileContext


class CodeGenerator(ABC):
    @abstractmethod
    def generate(self, context: CompileContext, output_dir: Path) -> None: ...
