import json

import pytest
from click.testing import CliRunner

from yaml_api_generator.cli import cli
from tests.conftest import VALID_DIR, INVALID_DIR


def test_compile_valid_yaml_generates_fastapi(tmp_path):
    runner = CliRunner()
    output = str(tmp_path / "out")
    result = runner.invoke(
        cli,
        [
            "compile",
            str(VALID_DIR / "basic-crud.yaml"),
            "--output",
            output,
        ],
    )
    assert result.exit_code == 0
    assert "fastapi" in result.output.lower() or "Generated" in result.output


def test_compile_target_drf(tmp_path):
    runner = CliRunner()
    output = str(tmp_path / "out")
    result = runner.invoke(
        cli,
        [
            "compile",
            str(VALID_DIR / "basic-crud.yaml"),
            "--output",
            output,
            "--target",
            "drf",
        ],
    )
    assert result.exit_code == 0
    assert (tmp_path / "out" / "backend" / "manage.py").exists()


def test_compile_target_raw(tmp_path):
    runner = CliRunner()
    output = str(tmp_path / "out")
    result = runner.invoke(
        cli,
        [
            "compile",
            str(VALID_DIR / "basic-crud.yaml"),
            "--output",
            output,
            "--target",
            "raw",
        ],
    )
    assert result.exit_code == 0
    assert (tmp_path / "out" / "backend" / "app.py").exists()


def test_compile_invalid_yaml_errors_json_stderr_exit1(tmp_path):
    runner = CliRunner()
    output = str(tmp_path / "out")
    result = runner.invoke(
        cli,
        [
            "compile",
            str(INVALID_DIR / "abstract-entity-in-repo.yaml"),
            "--output",
            output,
        ],
    )
    assert result.exit_code == 1


@pytest.mark.skip(reason="Starts uvicorn server, hard to test in unit tests")
def test_dev_starts_uvicorn():
    pass


@pytest.mark.skip(
    reason="Starts uvicorn server with raw ASGI, hard to test in unit tests"
)
def test_dev_raw_asgi_app():
    pass


@pytest.mark.skip(reason="Requires frontend module with UI block fixture")
def test_frontend_with_ui_block(tmp_path):
    pass


def test_frontend_without_ui_block_exits1():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "frontend",
            str(VALID_DIR / "basic-crud.yaml"),
        ],
    )
    assert result.exit_code == 1
