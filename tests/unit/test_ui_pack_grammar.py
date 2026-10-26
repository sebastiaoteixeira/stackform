"""A pack's manifest is the grammar of the ui block it renders."""

from pathlib import Path

import pytest
import yaml

from yaml_api_generator.generators.frontend.packs.loader import load_pack
from yaml_api_generator.generators.frontend.renderer import render_templates
from yaml_api_generator.parsers.errors import ConfigErrors
from yaml_api_generator.parsers.ui_parser import build_generator_context
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

ROOT = Path(__file__).resolve().parents[2]

SPEC = {
    "version": "0.3",
    "api": {"basePath": "/api", "version": "v1"},
    "datastores": {"local": {"type": "postgres", "dsn": "sqlite+aiosqlite:///grammar.sqlite", "default": True}},
    "entities": {
        "writer": {"fields": {"id": {"type": "id"}, "name": {"type": "string", "required": True}}},
        "post": {
            "fields": {
                "id": {"type": "id"},
                "title": {"type": "string", "required": True},
                "writer": {"type": "ref", "ref": "writer"},
            }
        },
    },
    "repositories": {"writers": {"entity": "writer"}, "posts": {"entity": "post"}},
    "services": {"writers": {"repository": "writers"}, "posts": {"repository": "posts"}},
    "controllers": {
        "writers": {"service": "writers", "base_path": "/writers", "access": "public"},
        "posts": {"service": "posts", "base_path": "/posts", "access": "public"},
    },
}


BLOG = str(ROOT / "examples/packs/blog")


def _context(tmp_path: Path, ui: dict, pack: str = "generic", **controllers):
    spec = {**SPEC, "controllers": {**SPEC["controllers"], **controllers}, "ui": {"frontend": {"pack": pack}, **ui}}
    (tmp_path / "spec.yaml").write_text(yaml.safe_dump(spec))
    result = load_and_generate_ir(tmp_path / "spec.yaml")
    return build_generator_context(result.ir, result.ui_block, load_pack(pack).manifest)


def _rejections(tmp_path: Path, ui: dict, pack: str = "generic") -> set[str]:
    with pytest.raises(ConfigErrors) as raised:
        _context(tmp_path, ui, pack)
    return {error.path for error in raised.value.errors}


def test_config_follows_the_pack_config_schema(tmp_path):
    assert _context(tmp_path, {"config": {"app_name": "Grammar", "colors": {"accent": "#123456"}}}).pack_config
    assert _rejections(tmp_path, {"config": {"theme": "dark"}}) == {"ui.config"}
    assert _rejections(tmp_path, {"config": {"colors": {"primary": "#123456"}}}) == {"ui.config.colors"}


@pytest.mark.parametrize(
    ("view", "path"),
    [
        ({"component": "crud", "props": {"collection": "post", "theme": "dark"}}, "ui.views.posts.props"),
        ({"component": "crud", "props": {"collection": "article"}}, "ui.views.posts.props.collection"),
        ({"component": "crud", "props": {}}, "ui.views.posts.props"),
        ({"component": "crud"}, "ui.views.posts"),
        ({"component": "crud", "props": {"collection": "post", "list": "carousel"}}, "ui.views.posts.props.list"),
        ({"component": "kanban", "props": {}}, "ui.views.posts.component"),
    ],
)
def test_views_pass_only_the_props_their_component_declares(tmp_path, view, path):
    assert _context(tmp_path, {"views": {"posts": {"path": "/posts", "component": "crud", "props": {"collection": "post"}}}})
    assert path in _rejections(tmp_path, {"views": {"posts": {"path": "/posts", **view}}})


def test_render_trees_bind_only_declared_props(tmp_path):
    def component(binding: str) -> dict:
        return {
            "components": {
                "post-table": {"props": {"source": {"required": True}}, "render": {"component": "crud", "props": {"collection": binding}}}
            },
            "views": {"posts": {"path": "/posts", "component": "post-table", "props": {"source": "post"}}},
        }

    assert _context(tmp_path, component("$source")).components["post-table"].render.props["collection"].value == "source"
    assert "ui.components.post-table.render.props.collection" in _rejections(tmp_path, component("$entity"))


@pytest.mark.parametrize(("collection", "accepted"), [
    ("post-feed", True), ("post-feed[id]", True), ("post", False), ("post-feed[", False), ("[id]", False),
])
def test_projection_props_name_a_declared_collection(tmp_path, collection, accepted):
    ui = {
        "collections": {"post-feed": {"fields": {"title": {"from": "post.title"}}}},
        "views": {"posts": {"path": "/posts", "component": "grid", "props": {"collection": collection}}},
    }

    if accepted:
        assert _context(tmp_path, ui, BLOG).views["posts"].props["collection"].value == collection
    else:
        assert _rejections(tmp_path, ui, BLOG) == {"ui.views.posts.props.collection"}


@pytest.mark.parametrize(
    ("source", "controllers", "message"),
    [
        ("post.title.name", {}, "'post.title' is not a ref"),
        ("post.writer.name", {"writers": {"service": "writers", "base_path": "/writers", "access": "public",
                                          "operations": {"get": False}}}, "'writer' serves no get route"),
    ],
)
def test_projections_follow_only_refs_the_ui_can_read(tmp_path, source, controllers, message):
    with pytest.raises(ValueError, match=message):
        _context(tmp_path, {"collections": {"feed": {"fields": {"field": {"from": source}}}}}, **controllers)


def test_projections_follow_refs_to_their_targets(tmp_path):
    feed = _context(tmp_path, {"collections": {"feed": {"fields": {"by": {"from": "post.writer.name"}}}}}).collections["feed"]

    assert (feed.entity, feed.fields["by"].source_field_path, feed.fields["by"].resolved_type) == (
        "post", ["writer", "name"], "string",
    )


def test_scaffold_entries_need_a_template(tmp_path):
    (tmp_path / "pack/templates").mkdir(parents=True)
    (tmp_path / "pack/pack.yaml").write_text(yaml.safe_dump({"name": "bare", "scaffold": ["main"]}))
    pack = load_pack(str(tmp_path / "pack"))
    context = _context(tmp_path, {}, str(tmp_path / "pack"))

    with pytest.raises(ValueError, match="Pack has no template 'scaffold/main.jinja'"):
        render_templates(pack, context)


@pytest.mark.parametrize("spec", ["examples/v02/api-with-ui.yaml", "examples/v02/api-with-admin.yaml"])
def test_example_packs_reach_the_api_only_through_the_shared_records(monkeypatch, spec):
    monkeypatch.chdir(ROOT)
    result = load_and_generate_ir(ROOT / spec)
    pack = load_pack(result.ui_block["frontend"]["pack"])
    files = {item.path: item.content for item in render_templates(pack, build_generator_context(result.ir, result.ui_block, pack.manifest))}

    assert "src/__generated__/records.ts" in files
    assert not [path for path, content in files.items()
                if not path.endswith(("records.ts", "config.ts")) and ("fetch(" in content or "API_BASE_URL" in content)]
