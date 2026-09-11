import json
import textwrap
from pathlib import Path

import pytest

from yaml_api_generator.parsers.transformers.v02.access_transformer import (
    AccessTransformer,
)
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


SCHEMAS = Path(__file__).parents[2] / "src/yaml_api_generator/parsers/schemas"


def _parse_rule(rule, allow_where):
    _, rules, errors = AccessTransformer(allow_where=allow_where).parse_access(
        [rule], "controllers.posts.routes.list.access", set(), {}
    )
    return rules, errors


def test_v03_filter_key_reports_dedicated_error():
    rules, errors = _parse_rule({"then": "allow", "filter": "owner = principal.sub"}, True)

    assert rules is None
    assert [error.code for error in errors] == ["ACCESS_FILTER_REMOVED"]
    assert errors[0].path == "controllers.posts.routes.list.access[0].filter"


def test_v02_filter_key_remains_in_ir():
    rules, errors = _parse_rule({"then": "allow", "filter": "owner = principal.sub"}, False)

    assert errors == []
    assert rules[0].filter == "owner = principal.sub"


def test_filter_is_removed_only_from_v03_schema():
    v02 = json.loads((SCHEMAS / "yaml-spec-v0.2.schema.json").read_text())
    v03 = json.loads((SCHEMAS / "yaml-spec-v0.3.schema.json").read_text())

    assert "filter" in v02["$defs"]["AccessRule"]["properties"]
    assert "filter" not in v03["$defs"]["AccessRule"]["properties"]


def test_v03_filter_aborts_full_spec_load(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        textwrap.dedent(
            """
            version: "0.3"
            api:
              name: removed-filter
              basePath: /api
            entities:
              post:
                fields:
                  id: {type: id}
            repositories:
              posts:
                entity: post
            services:
              listPosts:
                repository: posts
                operation: list
            controllers:
              posts:
                base_path: /posts
                routes:
                  list:
                    service: listPosts
                    method: GET
                    path: ""
                    access:
                      - then: allow
                        filter: owner = principal.sub
            """
        )
    )

    with pytest.raises(ConfigErrors) as raised:
        load_and_generate_ir(str(spec))

    assert "ACCESS_FILTER_REMOVED" in {error.code for error in raised.value.errors}
