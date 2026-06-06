import pytest

from yaml_api_generator.parsers.transformers.path_validation import (
    validate_spec_paths,
)


def _route(method: str, path: str, service: str = "svc") -> dict:
    return {"method": method, "path": path, "service": service, "access": "public"}


def _codes(controllers: dict, api: dict | None = None) -> set[str]:
    spec = {"controllers": controllers}
    if api is not None:
        spec["api"] = api
    return {error.code for error in validate_spec_paths(spec)}


# ---- ROUTE_PATH_DUPLICATE ----

def test_same_method_and_full_path_across_controllers_rejected():
    controllers = {
        "a": {"base_path": "/posts", "routes": {"list": _route("GET", "")}},
        "b": {"base_path": "/posts", "routes": {"list": _route("GET", "")}},
    }
    assert "ROUTE_PATH_DUPLICATE" in _codes(controllers)


def test_same_method_and_full_path_within_controller_rejected():
    controllers = {
        "a": {
            "base_path": "/posts",
            "routes": {
                "list": _route("GET", ""),
                "list_again": _route("GET", ""),
            },
        }
    }
    assert "ROUTE_PATH_DUPLICATE" in _codes(controllers)


def test_full_path_collision_via_base_path_and_route_path_rejected():
    # /api + /posts/extra (route) collides with /api/posts + /extra (route).
    controllers = {
        "a": {"base_path": "", "routes": {"r": _route("GET", "/posts/extra")}},
        "b": {"base_path": "/posts", "routes": {"r": _route("GET", "/extra")}},
    }
    assert "ROUTE_PATH_DUPLICATE" in _codes(controllers)


def test_shared_base_path_with_disjoint_paths_accepted():
    controllers = {
        "posts": {
            "base_path": "/posts",
            "routes": {
                "get": _route("GET", "/{id}"),
                "list": _route("GET", ""),
            },
        },
        "comments": {
            "base_path": "/posts",
            "routes": {
                "list": _route("GET", "/{post_id}/comments"),
                "get": _route("GET", "/{post_id}/comments/{id}"),
            },
        },
    }
    assert _codes(controllers) == set()


def test_same_path_different_method_accepted():
    controllers = {
        "a": {
            "base_path": "/posts",
            "routes": {
                "list": _route("GET", ""),
                "create": _route("POST", ""),
            },
        }
    }
    assert _codes(controllers) == set()


def test_method_case_insensitive_collision_rejected():
    controllers = {
        "a": {
            "base_path": "/posts",
            "routes": {
                "list": _route("get", ""),
                "list2": _route("GET", ""),
            },
        }
    }
    assert "ROUTE_PATH_DUPLICATE" in _codes(controllers)


def test_api_version_factored_into_full_path():
    # Same composed path only because the version prefix matches both.
    controllers = {
        "a": {"base_path": "/x", "routes": {"r": _route("GET", "")}},
        "b": {"base_path": "/x", "routes": {"r": _route("GET", "")}},
    }
    assert "ROUTE_PATH_DUPLICATE" in _codes(
        controllers, api={"basePath": "/api", "version": "v1"}
    )


# ---- CONTROLLER_BASE_PATH_INVALID ----

def test_base_path_with_param_token_rejected():
    controllers = {"a": {"base_path": "/tenants/{id}", "routes": {}}}
    assert "CONTROLLER_BASE_PATH_INVALID" in _codes(controllers)


@pytest.mark.parametrize("base", ["posts", "/posts/", "/po sts", "/posts!"])
def test_malformed_base_path_rejected(base):
    controllers = {"a": {"base_path": base, "routes": {}}}
    assert "CONTROLLER_BASE_PATH_INVALID" in _codes(controllers)


@pytest.mark.parametrize("base", ["", "/posts", "/api/v1", "/my-entity", "/a.b"])
def test_well_formed_base_path_accepted(base):
    controllers = {"a": {"base_path": base, "routes": {}}}
    assert _codes(controllers) == set()


def test_malformed_base_path_skips_route_checks():
    # A controller with an unusable base_path is reported once, not compounded
    # by spurious route-collision noise built on a broken prefix.
    controllers = {"a": {"base_path": "/x/{id}", "routes": {"r": _route("GET", "")}}}
    assert _codes(controllers) == {"CONTROLLER_BASE_PATH_INVALID"}
