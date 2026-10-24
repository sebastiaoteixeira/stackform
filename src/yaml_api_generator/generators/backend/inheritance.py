"""What a generated service or repository class declares itself and what it inherits from the abstract one it extends."""

from yaml_api_generator.ir import IRServiceBase
from yaml_api_generator.utils.strings import to_pascal_case

from .compile_context import CompileContext


def base_class(base: str | None, suffix: str) -> dict[str, str] | None:
    """The sibling module and class a generated class extends, or None when it extends nothing."""
    if base is None:
        return None
    return {"module": f".{base}", "class_name": f"{to_pascal_case(base)}{suffix}"}


def service_base_class(base: IRServiceBase | None) -> dict[str, str] | None:
    return base_class(base and base.name, "Service")


def own_service_operations(operations: dict[str, str | None], base: IRServiceBase | None) -> dict[str, str | None]:
    """The operations a service implements itself, mapped to their handler or None for its repository's."""
    inherited = base.operations.items() if base else {}.items()
    return {name: handler for name, handler in operations.items() if (name, handler) not in inherited}


def route_operations(col_data: dict) -> dict[str, str | None]:
    """The non-generated operations the routes of one service run, mapped as ``own_service_operations`` expects."""
    return {route.operation: route.handler for route in col_data["routes"] if route.runs_operation}


def own_repository_operations(context: CompileContext, name: str) -> list[dict]:
    """The query operations a repository declares itself rather than inherits."""
    inherited = context.repository_operations.get(context.repository_inherits.get(name), [])
    return [
        op for op in context.repository_operations.get(name, [])
        if op["query"] is not None and op not in inherited
    ]


def repository_base_class(context: CompileContext, name: str) -> dict[str, str] | None:
    return base_class(context.repository_inherits.get(name), "Repository")
