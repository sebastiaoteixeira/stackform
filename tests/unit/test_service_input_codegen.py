import compileall
import importlib.util
import subprocess
import sys
import textwrap

import pytest

from tests.conftest import VALID_DIR
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir


def _context():
    document = load_and_generate_ir(str(VALID_DIR / "v03-service-input.yaml")).ir
    return build_context(document)


def _load_helper(path):
    spec = importlib.util.spec_from_file_location("generated_service_inputs", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_route_descriptors_carry_service_contract():
    routes = {route.operation: route for route in _context().routes}

    assert routes["archive"].service_input == {
        "postId": {"type": "string"}
    }
    assert routes["archive"].service_forwarding == {
        "lookup": {"symbol": ["postId"]},
        "state": {"literal": "archived"},
    }
    assert routes["notify"].collection is None
    assert routes["notify"].service_forwarding == {
        "id": {"symbol": ["postId"]}
    }


@pytest.mark.parametrize(
    ("generator", "helper"),
    [
        (FastAPIGenerator(), "dependencies/service_inputs.py"),
        (DRFGenerator(), "api/service_inputs.py"),
        (RawASGIGenerator(), "service_inputs.py"),
    ],
)
def test_generated_backends_compile_and_validate_service_inputs(
    generator, helper, tmp_path
):
    generator.generate(_context(), tmp_path)

    assert compileall.compile_dir(str(tmp_path), quiet=1)
    generated = _load_helper(tmp_path / helper)
    fields = {"postId": {"type": "string"}}
    forwarding = {"id": {"symbol": ["postId"]}}
    assert generated.prepare_service_inputs(
        {"postId": "path-value"},
        {"postId": "spoofed"},
        fields,
        forwarding,
    ) == {"id": "path-value"}
    with pytest.raises(ValueError, match="Missing required inputs"):
        generated.prepare_service_inputs({}, {}, fields, forwarding)


def test_fastapi_emits_repository_and_handler_forwarding(tmp_path):
    FastAPIGenerator().generate(_context(), tmp_path)

    repository_route = (tmp_path / "routes/posts.py").read_text()
    handler_route = (tmp_path / "routes/_handlers.py").read_text()
    assert "'state': {'literal': 'archived'}" in repository_route
    assert "operation_bindings({**_path, **_service_inputs}" in repository_route
    assert "inputs=service_inputs" in handler_route


def test_fastapi_generated_routes_forward_values_end_to_end(tmp_path):
    FastAPIGenerator().generate(_context(), tmp_path)
    script = textwrap.dedent(
        f"""
        import sys
        import types
        sys.path.insert(0, {str(tmp_path)!r})

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from dependencies.repositories import get_posts_repository
        from routes._handlers import router as handler_router
        from routes.posts import router as posts_router

        handler_module = types.ModuleType("tests.support.service_input_handler")

        async def notify(request):
            return request.inputs

        handler_module.notify = notify
        sys.modules[handler_module.__name__] = handler_module

        from dependencies.operations import resolve
        from repositories.posts import PostsRepository

        class RecordingRepository(PostsRepository):
            def __init__(self):
                pass

            async def run_operation(self, query, bindings):
                return {{"filter": resolve(query["filter"], bindings)}}

        app = FastAPI()
        app.include_router(posts_router)
        app.include_router(handler_router)
        app.dependency_overrides[get_posts_repository] = RecordingRepository
        client = TestClient(app)

        response = client.post("/posts/p1/archive")
        assert response.status_code == 200
        assert response.json() == {{"filter": {{"id": "p1", "state": "archived"}}}}

        response = client.post("/notifications/p2")
        assert response.status_code == 200
        assert response.json() == {{"id": "p2"}}
        """
    )

    subprocess.run([sys.executable, "-c", script], check=True)


def test_raw_emits_repository_and_handler_forwarding(tmp_path):
    RawASGIGenerator().generate(_context(), tmp_path)

    repository_route = (tmp_path / "routes/posts.py").read_text()
    handler_route = (tmp_path / "routes/handlers.py").read_text()
    assert "repo.archive(operation_bindings({**url_params, **service_inputs}" in repository_route
    assert "inputs=service_inputs" in handler_route


def test_drf_emits_repository_and_handler_forwarding(tmp_path):
    DRFGenerator().generate(_context(), tmp_path)

    repository_route = (tmp_path / "api/views/posts.py").read_text()
    handler_route = (tmp_path / "api/views/_handlers.py").read_text()
    assert "repo.archive(operation_bindings({**path_params, **service_inputs}" in repository_route
    assert "inputs=service_inputs" in handler_route
