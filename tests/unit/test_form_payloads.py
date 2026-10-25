"""The generated UI sends bodies that both development servers and a generated FastAPI app accept and store as entered."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.unit.support import form_payloads
from tests.unit.support.form_payloads import EXPECTED, FIELDS_MODULE, NODE, scenario, spec
from tests.unit.support.payload_requests import JWT_SECRET, SQL_STORE
from tests.unit.support.scenarios import run_generated
from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.server import build_app, build_raw_app

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.fixture
def project(tmp_path, monkeypatch) -> tuple[Path, Path]:
    """The spec and the FastAPI project generated from it, whose frontend's fields module the scenario runs."""
    monkeypatch.setenv("YAML_API_DB_STORE_DSN", f"sqlite+aiosqlite:///{tmp_path / 'dev.sqlite'}")
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(spec(SQL_STORE))
    output = tmp_path / "fastapi"
    compile_project(yaml_file=str(spec_file), output_dir=str(output), target="fastapi")
    monkeypatch.setenv(FIELDS_MODULE, str(output / "frontend" / "src" / "__generated__" / "fields.ts"))
    return spec_file, output


@pytest.mark.parametrize("build", [build_app, build_raw_app], ids=["fastapi", "raw"])
def test_dev_server_accepts_form_payloads(project, build):
    spec_file, _ = project
    with TestClient(build(str(spec_file))) as client:
        assert scenario(client) == EXPECTED


def test_generated_fastapi_accepts_form_payloads(project):
    _, output = project
    backend = output / "backend"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{backend / 'generated.sqlite'}"}
    assert run_generated(backend, form_payloads.__name__, env) == EXPECTED


def test_every_form_component_renders_from_the_shared_field_input(project):
    _, output = project
    pages = output / "frontend" / "src" / "pages"
    forms = [pages / f"{name}.tsx" for name in ("ItemsForm", "SectionedForm", "PreviewedForm", "ModalForm", "Rows", "Sheet", "Bulk")]
    assert all("formData" not in page.read_text() for page in forms)
    assert all("../__generated__/fields" in page.read_text() or "useRecordForm" in page.read_text() for page in forms)
