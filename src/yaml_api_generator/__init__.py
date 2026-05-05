"""
YAML API Generator - Generate full-stack applications from YAML specifications.

This package provides tools to compile YAML API specifications into production-ready
backend and frontend code. Key components:

- IR (Intermediate Representation): Structured API definitions
- Parsers: YAML to IR conversion with validation
- Generators: IR to code (FastAPI, DRF, Raw ASGI)
- Server: Runtime request processing pipeline
- Compiler: Orchestrates the full compilation process

Public API:
- IR classes (IRApi, IRCollection, IRRoute, etc.)
- Pipeline for runtime request handling
- Parsing utilities (load_and_generate_ir, ConfigError)
- Optional: PlanCompiler, RuntimePlan (if dependencies available)
"""

from .ir import (
    IRApi,
    IRCollection,
    IRDocument,
    IRIdentityCollection,
    IROperations,
    IRRoute,
)
from .server import Pipeline

__all__ = [
    "IRApi",
    "IRCollection",
    "IRDocument",
    "IRIdentityCollection",
    "IROperations",
    "IRRoute",
    "Pipeline",
]

try:
    from .parsers.yaml_parser import ConfigError, ConfigErrors, load_and_generate_ir

    __all__.extend(["ConfigError", "ConfigErrors", "load_and_generate_ir"])
except ModuleNotFoundError:
    pass

try:
    from .plan_compiler import PipelineBuilder, PlanCompiler

    __all__.extend(["PipelineBuilder", "PlanCompiler"])
except ModuleNotFoundError:
    pass

try:
    from .runtime_plan import RoutePlan, RuntimePlan, StepDescriptor

    __all__.extend(["RoutePlan", "RuntimePlan", "StepDescriptor"])
except ModuleNotFoundError:
    pass
