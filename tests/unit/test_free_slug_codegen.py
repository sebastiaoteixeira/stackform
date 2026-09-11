import compileall
import subprocess
import sys
import textwrap

import pytest
import yaml

from tests.conftest import VALID_DIR
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.transformers.symbol_validation import (
    ROUTE_LOCATOR_FIELD_UNKNOWN,
    validate_spec_symbols,
)
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir


def _context(fixture: str = "v03-free-slug-fetch.yaml"):
    return build_context(load_and_generate_ir(str(VALID_DIR / fixture)).ir)


def test_v03_route_descriptors_capture_complete_record_predicate():
    routes = _context().routes

    assert {route.record_id_param for route in routes} == {"memberId"}
    assert {tuple(route.record_parent_params) for route in routes} == {("orgId",)}
    assert {tuple(route.record_criteria) for route in routes} == {
        (("orgId", "orgId"), ("id", "memberId"))
    }
    assert {route.django_path for route in routes} == {
        "orgs/<str:orgId>/members/<str:memberId>"
    }


def test_v02_route_descriptors_keep_literal_id_contract():
    get_route = next(
        route for route in _context("basic-crud.yaml").routes if route.operation == "get"
    )

    assert get_route.record_id_param == "id"
    assert get_route.record_parent_params == []
    assert get_route.record_criteria == [("id", "id")]


def test_unknown_parent_scope_field_is_rejected_at_build_time():
    spec = yaml.safe_load((VALID_DIR / "v03-free-slug-fetch.yaml").read_text())
    spec["controllers"]["members"]["routes"]["get"]["path"] = (
        "/{tenantId}/members/{memberId}"
    )

    errors = validate_spec_symbols(spec)

    assert [error.code for error in errors] == [ROUTE_LOCATOR_FIELD_UNKNOWN]
    assert errors[0].path == "controllers.members.routes.get.path"


@pytest.mark.parametrize(
    "generator", [FastAPIGenerator(), DRFGenerator(), RawASGIGenerator()]
)
def test_all_generated_backends_byte_compile(generator, tmp_path):
    generator.generate(_context(), tmp_path)

    assert compileall.compile_dir(str(tmp_path), quiet=1)


def test_fastapi_generated_routes_execute_with_full_scope(tmp_path):
    FastAPIGenerator().generate(_context(), tmp_path)
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(tmp_path)!r})

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from dependencies.services import get_members_service
        from routes.members import router

        class RecordingService:
            async def get_by(self, criteria):
                return criteria

            async def delete_by(self, criteria):
                return criteria

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_members_service] = RecordingService
        client = TestClient(app)

        get_response = client.get("/orgs/o1/members/m1")
        assert get_response.status_code == 200
        assert get_response.json() == {{"orgId": "o1", "id": "m1"}}

        delete_response = client.delete("/orgs/o1/members/m1")
        assert delete_response.status_code == 200
        assert delete_response.json() == {{"orgId": "o1", "id": "m1"}}
        """
    )

    subprocess.run([sys.executable, "-c", script], check=True)


def test_generated_backends_use_atomic_scoped_operations(tmp_path):
    fastapi_dir = tmp_path / "fastapi"
    drf_dir = tmp_path / "drf"
    raw_dir = tmp_path / "raw"
    FastAPIGenerator().generate(_context(), fastapi_dir)
    DRFGenerator().generate(_context(), drf_dir)
    RawASGIGenerator().generate(_context(), raw_dir)

    fastapi_routes = (fastapi_dir / "routes" / "members.py").read_text()
    drf_urls = (drf_dir / "api" / "urls.py").read_text()
    drf_views = (drf_dir / "api" / "views" / "members.py").read_text()
    raw_routes = (raw_dir / "routes" / "members.py").read_text()

    criteria = '{"orgId": orgId, "id": memberId}'
    assert f"svc.update_by({criteria}" in fastapi_routes
    assert f"svc.replace_by({criteria}" in fastapi_routes
    assert f"service.update_by({criteria}" in drf_views
    assert f"service.replace_by({criteria}" in drf_views
    assert "<str:orgId>/members/<str:memberId>" in drf_urls
    assert (
        'service.delete_by({"orgId": url_params["orgId"], '
        '"id": url_params["memberId"]})'
    ) in raw_routes


def test_v02_fastapi_generation_still_uses_id_lookup(tmp_path):
    FastAPIGenerator().generate(_context("basic-crud.yaml"), tmp_path)
    routes = (tmp_path / "routes" / "posts.py").read_text()

    assert "async def get_posts(id: str" in routes
    assert "return await svc.get(id)" in routes
