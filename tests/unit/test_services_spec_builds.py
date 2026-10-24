"""The services behaviour specs build cleanly for targets the integration suite cannot serve."""

import compileall
from pathlib import Path

from yaml_api_generator.cli.compiler import compile_project

_SPEC = Path(__file__).parents[1] / "integration" / "specs" / "services_mongo" / "spec.yaml"


def test_services_spec_builds_for_drf(tmp_path, monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("MONGO_DB", "services")
    compile_project(yaml_file=str(_SPEC), output_dir=str(tmp_path), target="drf")

    service = (tmp_path / "backend" / "api" / "services" / "tasks.py").read_text()
    assert compileall.compile_dir(str(tmp_path / "backend"), quiet=2)
    assert "self._repo.retitle(request.bindings)" in service
    assert "invoke('hooks.echo', request)" in service
