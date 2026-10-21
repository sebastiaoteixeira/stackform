"""Request payloads are validated by their field configs in every consumer.

The shared payload scenario runs against both development servers and a
generated FastAPI app executed in a subprocess. DRF cannot run here, so its
generated serializers are checked to delegate to the shared validator.
"""

import ast
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.unit.support.payload_requests import (
    EXPECTED,
    JWT_SECRET,
    MONGO_STORE,
    SQL_STORE,
    scenario,
    spec,
)
from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.server import build_app, build_raw_app


ROOT = Path(__file__).parents[2]


@pytest.fixture
def spec_file(tmp_path, monkeypatch):
    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path / 'dev.sqlite'}")
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    path = tmp_path / "spec.yaml"
    path.write_text(spec(SQL_STORE))
    return str(path)


def _generate(spec_file: str, target: str) -> Path:
    output = Path(spec_file).parent / target
    compile_project(yaml_file=spec_file, output_dir=str(output), target=target)
    return output / "backend"


@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["fastapi", "raw"])
def test_dev_server_validates_payloads(spec_file, build):
    with TestClient(build(spec_file)) as client:
        assert scenario(client) == EXPECTED


_RUNNER = f"""
import json, sys
sys.path.append({str(ROOT)!r})
from fastapi.testclient import TestClient
from tests.unit.support.payload_requests import scenario
import app

with TestClient(app.app) as client:
    print(json.dumps(scenario(client)))
"""


def test_generated_fastapi_validates_payloads(spec_file):
    backend = _generate(spec_file, "fastapi")
    result = subprocess.run(
        [sys.executable, "-c", _RUNNER],
        cwd=backend,
        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{backend / 'generated.sqlite'}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == EXPECTED


@pytest.fixture
def mongo_spec_file(tmp_path):
    path = tmp_path / "mongo-spec.yaml"
    path.write_text(spec(MONGO_STORE))
    return str(path)


def test_generated_drf_serializers_validate_through_the_shared_validator(mongo_spec_file):
    api = _generate(mongo_spec_file, "drf") / "api"
    assert "conform_object(self.properties, data" in (api / "payloads.py").read_text()
    assert (api / "fields.py").read_text() == (ROOT / "src/yaml_api_generator/runtime/fields.py").read_text()
    serializers = (api / "serializers" / "items.py").read_text()
    assert 'ItemsUpdatePayload = partial(ItemsFields, "ItemsUpdatePayload")' in serializers
    assert "class ItemsCreatePayload(ItemsFields):" in serializers
    assert "NoteInput(data=request.data)" in (api / "views" / "notes.py").read_text()


def _is_field_config(node: ast.expr) -> bool:
    return isinstance(node, ast.Dict) and any(
        isinstance(key, ast.Constant) and key.value == "type" for key in node.keys
    )


def _field_declarations(source: str) -> Counter:
    """Each field a module declares, as a class annotation or a field config map entry.

    A declaration is its name with its type, so same-named fields of unrelated
    payloads stay distinct while a field copied into a sibling payload repeats.
    """
    nodes = list(ast.walk(ast.parse(source)))
    annotations = (
        (node.target.id, ast.unparse(node.annotation))
        for node in nodes
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        and node.target.id != "properties"
    )
    configured = (
        (key.value, ast.unparse(value))
        for node in nodes
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant) and _is_field_config(value)
    )
    return Counter(annotations) + Counter(configured)


@pytest.mark.parametrize("target,modules", [
    ("fastapi", "models/*.py"),
    ("drf", "api/serializers/*.py"),
    ("raw", "validation.py"),
])
def test_no_generated_payload_module_repeats_a_field_declaration(mongo_spec_file, target, modules):
    sources = {module.name: module.read_text() for module in _generate(mongo_spec_file, target).glob(modules)}
    assert "items.py" in sources or "validation.py" in sources
    repeated = {
        name: [field for field, count in _field_declarations(source).items() if count > 1]
        for name, source in sources.items()
    }
    assert repeated == {name: [] for name in sources}
