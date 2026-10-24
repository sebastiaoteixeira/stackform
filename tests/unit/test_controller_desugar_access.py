import pytest
from yaml_api_generator.parsers.desugar.controller_desugarer import ControllerDesugarer


def _expanded_services() -> dict:
    return {
        "list-users": {"type": "list"},
        "get-users": {"type": "get"},
        "create-users": {"type": "create"},
    }


def test_routes_form_access_override_applied() -> None:
    controllers = {
        "users": {
            "service": "users",
            "access": "authenticated",
            "routes": {
                "get": {"access": ["role:admin"]},
            },
        }
    }
    ControllerDesugarer().desugar(controllers, _expanded_services())
    routes = controllers["users"]["routes"]
    assert routes["get"]["access"] == ["role:admin"]


def test_routes_form_other_ops_inherit_base_access() -> None:
    controllers = {
        "users": {
            "service": "users",
            "access": "authenticated",
            "routes": {
                "get": {"access": ["role:admin"]},
            },
        }
    }
    ControllerDesugarer().desugar(controllers, _expanded_services())
    routes = controllers["users"]["routes"]
    assert routes["list"]["access"] == "authenticated"
    assert routes["create"]["access"] == "authenticated"


def test_operations_form_access_override_unchanged() -> None:
    controllers = {
        "users": {
            "service": "users",
            "access": "public",
            "operations": {
                "list": {"access": "authenticated"},
            },
        }
    }
    ControllerDesugarer().desugar(controllers, _expanded_services())
    routes = controllers["users"]["routes"]
    assert routes["list"]["access"] == "authenticated"
    assert routes["get"]["access"] == "public"
    assert routes["create"]["access"] == "public"


def test_routes_form_access_takes_priority_over_operations_form() -> None:
    controllers = {
        "users": {
            "service": "users",
            "access": "public",
            "operations": {
                "get": {"access": "authenticated"},
            },
            "routes": {
                "get": {"access": ["role:admin"]},
            },
        }
    }
    ControllerDesugarer().desugar(controllers, _expanded_services())
    routes = controllers["users"]["routes"]
    assert routes["get"]["access"] == ["role:admin"]


def test_explicit_controller_without_access_is_public() -> None:
    controllers = {
        "stats": {
            "routes": {"count": {"service": "count-posts", "method": "GET", "path": "/stats"}},
        }
    }
    ControllerDesugarer().desugar(controllers, _expanded_services())
    assert controllers["stats"]["routes"]["count"]["access"] == "public"


def test_explicit_controller_operations_override_route_method_and_path() -> None:
    controllers = {
        "stats": {
            "access": "authenticated",
            "routes": {"count": {"service": "count-posts", "method": "GET", "path": "/stats"}},
            "operations": {"count": {"method": "POST", "path": "/stats/run"}},
        }
    }
    ControllerDesugarer().desugar(controllers, _expanded_services())
    route = controllers["stats"]["routes"]["count"]
    assert (route["method"], route["path"], route["access"]) == ("POST", "/stats/run", "authenticated")
