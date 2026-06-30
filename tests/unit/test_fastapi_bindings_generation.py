import textwrap

from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir


_SPEC = """
    version: "0.2"
    api: { basePath: "" }
    mongo:
      uri: mongodb://localhost:27017
      database: testdb
    entities:
      post:
        fields:
          id: { type: id }
          orgId: { type: string }
          title: { type: string }
    repositories:
      posts:
        entity: post
        operations:
          byOrg:
            query:
              command: find
              filter: { orgId: "$principal.record.orgId" }
    services:
      posts: { repository: posts }
      byOrg: { repository: posts, operation: byOrg }
    controllers:
      posts:
        base_path: /posts
        routes:
          list: { service: posts, method: GET, path: "", access: public }
          byOrg: { service: byOrg, method: GET, path: "/by-org", access: public }
"""


def test_bindings_module_emitted_for_custom_operations(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(textwrap.dedent(_SPEC))
    result = load_and_generate_ir(str(spec_path))
    ctx = build_context(result.ir)
    gen = FastAPIGenerator()
    out = tmp_path / "out"
    gen.generate(ctx, out)

    assert (out / "dependencies" / "bindings.py").exists()
    route_content = (out / "routes" / "posts.py").read_text()
    assert "resolve_filter" in route_content
    assert "dependencies.bindings" in route_content


def test_bindings_module_absent_without_custom_operations(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(textwrap.dedent("""
        version: "0.2"
        api: { basePath: "" }
        mongo:
          uri: mongodb://localhost:27017
          database: testdb
        entities:
          post:
            fields:
              id: { type: id }
              title: { type: string }
        repositories:
          posts: { entity: post }
        services:
          posts: { repository: posts }
        controllers:
          posts:
            base_path: /posts
            routes:
              list: { service: posts, method: GET, path: "", access: public }
    """))
    result = load_and_generate_ir(str(spec_path))
    ctx = build_context(result.ir)
    gen = FastAPIGenerator()
    out = tmp_path / "out"
    gen.generate(ctx, out)

    assert not (out / "dependencies" / "bindings.py").exists()
