"""Operation names that would shadow a generated repository or service member are rejected by the schema."""

import shutil
from pathlib import Path

import pytest
import yaml

from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

_SPEC = Path(__file__).parents[1] / "integration" / "specs" / "services_mongo" / "spec.yaml"


@pytest.fixture(autouse=True)
def _mongo_settings(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("MONGO_DB", "services")


def _renamed(spec: dict, section: str, owner: str, old: str, new: str) -> dict:
    operations = spec[section][owner]["operations"]
    operations[new] = operations.pop(old)
    return spec


def _load(spec: dict, tmp_path: Path):
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec))
    shutil.copytree(_SPEC.parent / "hooks", tmp_path / "hooks")
    return load_and_generate_ir(str(path))


@pytest.mark.parametrize("name", ["insert", "paginate", "find_one", "run_operation", "get_by", "upsert_by", "class"])
@pytest.mark.parametrize(("section", "owner", "old"), [
    ("repositories", "tasks", "retitle"),
    ("services", "tasks", "echo"),
    ("controllers", "tasks", "echo"),
])
def test_operation_named_after_a_generated_member_is_rejected(tmp_path, section, owner, old, name):
    spec = _renamed(yaml.safe_load(_SPEC.read_text()), section, owner, old, name)
    with pytest.raises(ConfigErrors) as raised:
        _load(spec, tmp_path)
    assert any(error.code == "SCHEMA_VALIDATION_ERROR" for error in raised.value.errors)


def test_route_names_of_a_controller_without_service_stay_free(tmp_path):
    spec = yaml.safe_load(_SPEC.read_text())
    totals = spec["controllers"]["totals"]
    totals["routes"]["tasks-total"] = totals["routes"].pop("tasks")
    totals["operations"]["tasks-total"] = totals["operations"].pop("tasks")
    assert _load(spec, tmp_path).ir is not None
