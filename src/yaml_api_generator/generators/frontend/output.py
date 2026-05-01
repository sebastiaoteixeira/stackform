from dataclasses import dataclass


@dataclass
class OutputFile:
    path: str
    content: str
    zone: str
