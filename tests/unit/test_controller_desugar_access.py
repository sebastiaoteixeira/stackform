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
