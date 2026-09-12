"""Generated backends must refuse to emit a spec that declares pagination.

Pagination is interpreted by ``yaml-api run`` only. The three code generators
emit an unbounded ``service.list()``, so a spec that asked to page would build
into an app that silently returns every row; generation fails instead.
"""

import pytest

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

_SPEC = """
version: "0.3"
api:
  basePath: /api
  version: v1
datastores:
  store: {{ type: postgres, dsn: "postgresql+asyncpg://localhost/unused", default: true }}
entities:
  post:
    fields:
      id: {{ type: id }}
      title: {{ type: string }}
repositories:
  posts:
    entity: post
services:
  posts:
    repository: posts
controllers:
  posts:
    service: posts
    base_path: /posts
    access: "*"
{operations}
"""

_PAGINATED = """\
    operations:
      list:
        pagination:
          strategy: offset
          size: { default: 20, max: 100 }
"""

_UNPAGINATED = "    operations: {}\n"


def _context(tmp_path, operations: str):
    spec = tmp_path / "spec.yaml"
    spec.write_text(_SPEC.format(operations=operations))
    return build_context(load_and_generate_ir(str(spec)).ir)


@pytest.fixture(
    params=[FastAPIGenerator, DRFGenerator, RawASGIGenerator],
    ids=["fastapi", "drf", "raw"],
)
def generator(request):
    return request.param()


class TestPaginationRejected:
    def test_generation_fails(self, generator, tmp_path):
        with pytest.raises(ConfigErrors):
            generator.generate(_context(tmp_path, _PAGINATED), tmp_path / "out")

    def test_error_names_the_operation_and_backend(self, generator, tmp_path):
        with pytest.raises(ConfigErrors) as raised:
            generator.generate(_context(tmp_path, _PAGINATED), tmp_path / "out")
        (error,) = raised.value.errors
        assert error.code == "BACKEND_FEATURE_UNSUPPORTED"
        assert "pagination" in error.message
        assert "list" in error.message
        assert error.path == "controllers.posts.operations.list.pagination"
        assert error.hint

    def test_nothing_is_emitted(self, generator, tmp_path):
        output = tmp_path / "out"
        with pytest.raises(ConfigErrors):
            generator.generate(_context(tmp_path, _PAGINATED), output)
        assert not output.exists()


class TestUnpaginatedStillGenerates:
    def test_generation_succeeds(self, generator, tmp_path):
        output = tmp_path / "out"
        generator.generate(_context(tmp_path, _UNPAGINATED), output)
        assert any(output.rglob("*.py"))
