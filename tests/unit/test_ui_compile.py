"""A frontend rendering every component of the generic pack type-checks as the project it is generated into."""

import shutil
import subprocess

import pytest
import yaml

from tests.unit.support.live_apps import STACKFORM
from yaml_api_generator.generators.frontend.packs.loader import load_pack

NPM = shutil.which("npm")

SPEC = """
version: "0.3"

api:
  basePath: /api
  version: v1
  operations:
    defaults: { list: true, get: true, create: true, update: true, replace: false, delete: true }
    auth: { register: true, login: true }

datastores:
  local: { type: postgres, dsn: "sqlite+aiosqlite:///compile.sqlite", default: true }

entities:
  member:
    type: auth
    auth: { identifier: handle, via: password }
    roles:
      values: [admin, viewer]
      default: viewer
      hierarchy: { admin: [viewer] }
    fields:
      id: { type: id }
      handle: { type: string, required: true, unique: true }
      age: { type: number }
      active: { type: boolean, default: true }
  item:
    fields:
      id: { type: id }
      code: { type: string, required: true, unique: true }
      rank: { type: number, required: true }
      flag: { type: boolean, default: false }
      status: { type: enum, values: [draft, live], default: draft }
      stamp: { type: string, readonly: true }
      owner: { type: ref, ref: member }

repositories:
  members: { entity: member }
  items: { entity: item }

services:
  members: { repository: members }
  items: { repository: items }

controllers:
  members:
    service: members
    base_path: /members
    access: admin
    operations:
      register: { access: public }
      login: { access: public }
  items:
    service: items
    base_path: /items
    access: viewer
"""

REQUIRED_VALUES = {"collection": "item", "component": "list-table", "string": "Title", "array": []}


def _views() -> dict:
    """One view per component the pack renders (crud through its scaffold), given the props it requires."""
    pack = load_pack("generic")
    rendered = {"crud"} | {template.stem for template in (pack.templates_dir / "components").glob("*.jinja")}
    return {
        name: {
            "path": f"/{name}",
            "component": name,
            "props": {
                prop: REQUIRED_VALUES[spec.get("type")]
                for prop, spec in (component.get("props") or {}).items()
                if spec.get("required")
            },
        }
        for name, component in pack.manifest.components.items()
        if name in rendered
    }


@pytest.fixture(scope="module")
def frontend(tmp_path_factory):
    root = tmp_path_factory.mktemp("compile")
    spec = root / "spec.yaml"
    ui = {"ui": {"frontend": {"pack": "generic"}, "views": _views()}}
    spec.write_text(SPEC + yaml.safe_dump(ui, sort_keys=False))
    built = subprocess.run([STACKFORM, "build", str(spec), "frontend", "-o", str(root / "app")], capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    installed = subprocess.run(
        [NPM, "install", "--no-audit", "--no-fund", "--loglevel=error"], cwd=root / "app", capture_output=True, text=True
    )
    assert installed.returncode == 0, installed.stderr
    return root / "app"


@pytest.mark.skipif(NPM is None, reason="npm installs the generated project's compiler and types")
def test_every_pack_component_type_checks(frontend):
    compiled = subprocess.run(["npx", "--no-install", "tsc", "-b"], cwd=frontend, capture_output=True, text=True)

    assert compiled.returncode == 0, compiled.stdout
