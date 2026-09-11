"""Generation tests for request-bound access rules and DTO models.

Asserts the FastAPI generator emits the DTO model, wires the typed body and
request locals into the create route, and byte-compiles the backend.
"""

import compileall

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
from tests.conftest import VALID_DIR


def _generate(tmp_path):
    ctx = build_context(
        load_and_generate_ir(str(VALID_DIR / "request-access.yaml")).ir
    )
    FastAPIGenerator().generate(ctx, tmp_path)
    return ctx


def test_dto_model_emitted(tmp_path):
    ctx = _generate(tmp_path)
    assert [m.name for m in ctx.dto_models] == ["CreateMembership"]
    dto_module = (tmp_path / "models" / "_dto.py").read_text()
    assert "class CreateMembership(BaseModel):" in dto_module
    assert "Literal['admin', 'member', 'viewer']" in dto_module


def test_create_route_uses_typed_body_and_request_locals(tmp_path):
    _generate(tmp_path)
    route = (tmp_path / "routes" / "memberships.py").read_text()
    assert "from models._dto import CreateMembership" in route
    assert "payload: CreateMembership" in route
    assert '_request_body = payload.model_dump(mode="json")' in route
    assert "request: Request" not in route or "_request_query" in route


def test_generated_backend_byte_compiles(tmp_path):
    _generate(tmp_path)
    assert compileall.compile_dir(str(tmp_path), quiet=1)
