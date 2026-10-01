"""File routes derived from the get and update routes of collections with files."""

import pytest

from tests.conftest import INVALID_DIR, VALID_DIR
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

BASE = "/api/v1/documents/{id}/files"


@pytest.fixture(scope="module")
def ir():
    return load_and_generate_ir(str(VALID_DIR / "files-filesystem.yaml")).ir


def _shape(route):
    return route.action, route.method, route.path, route.field, route.item, route.source.operation


def test_routes_follow_source_order_then_field_order(ir):
    assert [_shape(route) for route in ir.file_routes] == [
        ("download", "GET", f"{BASE}/avatar", "avatar", False, "get"),
        ("download", "GET", f"{BASE}/attachments/{{fileId}}", "attachments", True, "get"),
        ("download", "GET", f"{BASE}/scans/{{fileId}}", "scans", True, "get"),
        ("download", "GET", f"{BASE}/contract", "contract", False, "get"),
        ("replace", "PUT", f"{BASE}/avatar", "avatar", False, "update"),
        ("remove", "DELETE", f"{BASE}/avatar", "avatar", False, "update"),
        ("replace", "PUT", f"{BASE}/attachments", "attachments", False, "update"),
        ("replace", "PUT", f"{BASE}/attachments/{{fileId}}", "attachments", True, "update"),
        ("remove", "DELETE", f"{BASE}/attachments/{{fileId}}", "attachments", True, "update"),
        ("replace", "PUT", f"{BASE}/scans", "scans", False, "update"),
        ("replace", "PUT", f"{BASE}/scans/{{fileId}}", "scans", True, "update"),
        ("remove", "DELETE", f"{BASE}/scans/{{fileId}}", "scans", True, "update"),
    ]


def test_readonly_field_is_download_only(ir):
    assert {route.action for route in ir.file_routes if route.field == "contract"} == {"download"}


def test_source_is_the_declared_route(ir):
    assert all(route.source in ir.routes for route in ir.file_routes)
    assert {route.collection for route in ir.file_routes} == {"documents"}


def test_collections_without_files_derive_nothing():
    ir = load_and_generate_ir(str(VALID_DIR / "files-s3.yaml")).ir
    assert {route.collection for route in ir.file_routes} == {"photos", "reports"}
    assert {route.action for route in ir.file_routes if route.collection == "photos"} == {
        "download", "replace", "remove",
    }


@pytest.mark.parametrize("fixture, path", [
    ("files-route-conflict.yaml", "PATCH /api/documents/{id}"),
    ("files-source-declares-file-id.yaml", "GET /api/documents/{fileId}"),
])
def test_conflicting_file_route_is_rejected(fixture, path):
    with pytest.raises(ConfigErrors) as raised:
        load_and_generate_ir(str(INVALID_DIR / fixture))
    assert [(error.code, error.path) for error in raised.value.errors] == [("FILE_ROUTE_CONFLICT", path)]
