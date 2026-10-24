import pytest
import yaml

from yaml_api_generator.parsers.transformers.ref_validation import validate_spec_refs
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


def _errors(fields: dict) -> list:
    return validate_spec_refs({"entities": {"author": {"fields": {}}, "post": {"fields": fields}}})


def test_ref_to_declared_entity_accepted():
    assert _errors({"authorId": {"type": "ref", "ref": "author"}}) == []


@pytest.mark.parametrize("field,path", [
    ({"type": "ref", "ref": "authors"}, "entities.post.fields.x.ref"),
    ({"type": "array", "items": {"type": "ref", "ref": "ghost"}}, "entities.post.fields.x.items.ref"),
    (
        {"type": "object", "properties": {"owner": {"type": "ref", "ref": "ghost"}}},
        "entities.post.fields.x.properties.owner.ref",
    ),
])
def test_ref_to_undeclared_entity_rejected(field, path):
    errors = _errors({"x": field})
    assert [(e.code, e.path) for e in errors] == [("REF_TARGET_NOT_FOUND", path)]


def test_ref_to_undeclared_entity_rejected_end_to_end(tmp_path):
    spec = {
        "version": "0.2",
        "api": {"basePath": "/api", "version": "v1"},
        "mongo": {"uri": "mongodb://localhost:27017", "database": "testdb"},
        "entities": {
            "post": {"fields": {"id": {"type": "id"}, "authorId": {"type": "ref", "ref": "posts"}}}
        },
        "repositories": {"posts": {"entity": "post"}},
        "services": {"posts": {"repository": "posts"}},
        "controllers": {"posts": {"service": "posts", "base_path": "/posts", "access": "public"}},
    }
    yaml_file = tmp_path / "spec.yaml"
    yaml_file.write_text(yaml.safe_dump(spec))
    with pytest.raises(ConfigErrors) as exc_info:
        load_and_generate_ir(str(yaml_file))
    assert {e.code for e in exc_info.value.errors} == {"REF_TARGET_NOT_FOUND"}
