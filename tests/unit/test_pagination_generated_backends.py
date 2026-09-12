import compileall
import json
import os
import subprocess
import sys
import textwrap

import pytest

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir


_SPEC = """
version: "0.3"
api:
  basePath: /api
  version: v1
datastores:
  store:
    type: postgres
    dsn: "postgresql+asyncpg://localhost/unused"
    default: true
entities:
  post:
    fields:
      id: { type: id }
      title: { type: string }
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
    access: public
{operations}
"""

_PAGINATED = """\
    operations:
      list:
        pagination:
          strategy: offset
          size: { default: 20, max: 100 }
          count: exact
          envelope: true
"""

_UNPAGINATED = "    operations: {}\n"


def _context(tmp_path, operations: str):
    spec = tmp_path / "spec.yaml"
    spec.write_text(_SPEC.replace("{operations}", operations))
    return build_context(load_and_generate_ir(str(spec)).ir)


@pytest.fixture(
    params=[FastAPIGenerator, DRFGenerator, RawASGIGenerator],
    ids=["fastapi", "drf", "raw"],
)
def generator(request):
    return request.param()


def test_every_backend_generates_compilable_pagination(generator, tmp_path):
    output = tmp_path / "out"
    generator.generate(_context(tmp_path, _PAGINATED), output)

    assert compileall.compile_dir(str(output), quiet=1)
    pagination = next(output.rglob("pagination.py"))
    sources = "\n".join(path.read_text() for path in output.rglob("*.py"))
    assert "def map_request(" in pagination.read_text()
    assert "async def paginate(" in sources
    assert "build_response(" in sources


def test_unpaginated_generation_keeps_bare_list_path(generator, tmp_path):
    output = tmp_path / "out"
    generator.generate(_context(tmp_path, _UNPAGINATED), output)

    route_sources = "\n".join(
        path.read_text()
        for path in output.rglob("*.py")
        if "route" in path.name or "routes" in str(path.parent)
    )
    assert "map_request(" not in route_sources
    assert "build_response(" not in route_sources
    assert any(output.rglob("*.py"))


def test_generated_fastapi_sql_keyset_round_trip(tmp_path):
    database = tmp_path / "generated.sqlite"
    spec = tmp_path / "keyset.yaml"
    spec.write_text(
        textwrap.dedent(
            f"""
            version: "0.3"
            api:
              basePath: /api
              operations:
                defaults:
                  list: true
                  create: true
            datastores:
              store:
                type: postgres
                dsn: sqlite+aiosqlite:///{database}
            entities:
              post:
                fields:
                  id: {{ type: id }}
                  score: {{ type: number, required: true }}
                  slug: {{ type: string, required: true, unique: true }}
            repositories:
              posts: {{ entity: post, datastore: store }}
            services:
              posts: {{ repository: posts }}
            controllers:
              posts:
                service: posts
                access: public
                operations:
                  list:
                    pagination:
                      strategy: keyset
                      size: {{ default: 2, max: 3 }}
                      sort:
                        - {{ field: score, dir: desc }}
                        - {{ field: slug, dir: asc }}
                      envelope: true
            """
        )
    )
    output = tmp_path / "backend"
    FastAPIGenerator().generate(
        build_context(load_and_generate_ir(str(spec)).ir),
        output,
    )

    script = textwrap.dedent(
        """
        import asyncio
        import json

        from dependencies.pagination import build_response, map_request
        from dependencies.postgres import close_db, connect_db, get_database
        from repositories.posts import PostsRepository
        from services.posts import PostsService

        CONFIG = {
            "strategy": "keyset",
            "size": {"default": 2, "max": 3},
            "count": "none",
            "on_overflow": "clamp",
            "envelope": True,
            "sort": [
                {"field": "score", "dir": "desc"},
                {"field": "slug", "dir": "asc"},
            ],
        }

        async def main():
            await connect_db()
            service = PostsService(PostsRepository(get_database()))
            for row in [
                {"score": 10, "slug": "alpha"},
                {"score": 30, "slug": "gamma"},
                {"score": 20, "slug": "beta"},
                {"score": 20, "slug": "epsilon"},
            ]:
                await service.create(row)
            first_query = {"limit": "2"}
            first = build_response(
                CONFIG,
                await service.list(map_request(CONFIG, first_query)),
                first_query,
            )
            second_query = {"limit": "2", "after": first["next"]}
            second = build_response(
                CONFIG,
                await service.list(map_request(CONFIG, second_query)),
                second_query,
            )
            print(json.dumps({"first": first, "second": second}, default=str))
            await close_db()

        asyncio.run(main())
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=output,
        env={**os.environ, "PYTHONPATH": str(output)},
        capture_output=True,
        text=True,
        check=True,
    )
    pages = json.loads(result.stdout)
    assert [item["slug"] for item in pages["first"]["items"]] == [
        "gamma",
        "beta",
    ]
    assert [item["slug"] for item in pages["second"]["items"]] == [
        "epsilon",
        "alpha",
    ]
    assert pages["first"]["hasMore"] is True
    assert pages["second"] == {
        "items": pages["second"]["items"],
        "hasMore": False,
        "next": None,
    }
