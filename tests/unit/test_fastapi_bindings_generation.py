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


def test_custom_operation_route_calls_the_repository_method(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(textwrap.dedent(_SPEC))
    out = tmp_path / "out"
    FastAPIGenerator().generate(build_context(load_and_generate_ir(str(spec_path)).ir), out)

    assert (out / "dependencies" / "operations.py").exists()
    assert (out / "dependencies" / "mongo_operations.py").exists()
    repository = (out / "repositories" / "posts.py").read_text()
    assert "async def byOrg(self, bindings: dict[str, Any]) -> Any:" in repository
    assert "'$principal.record.orgId'" in repository
    route_content = (out / "routes" / "posts.py").read_text()
    assert "svc.byOrg(_request)" in route_content
    assert "self._repo.byOrg(request.bindings)" in (out / "services" / "posts.py").read_text()
