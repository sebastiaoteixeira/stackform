import json
from pathlib import Path

from click.testing import CliRunner

from yaml_api_generator.cli import cli
from tests.conftest import VALID_DIR, INVALID_DIR


V03_EXAMPLES = Path(__file__).parents[2] / "examples" / "v03"


def test_compile_valid_yaml_generates_fastapi(tmp_path):
    runner = CliRunner()
    output = str(tmp_path / "out")
    result = runner.invoke(
        cli,
        [
            "build",
            str(VALID_DIR / "basic-crud.yaml"),
            "backend",
            "--output",
            output,
        ],
    )
    assert result.exit_code == 0
    assert "Backend generated" in result.output


def test_compile_target_drf(tmp_path):
    runner = CliRunner()
    output = str(tmp_path / "out")
    result = runner.invoke(
        cli,
        [
            "build",
            str(VALID_DIR / "basic-crud.yaml"),
            "backend",
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
            "build",
            str(VALID_DIR / "basic-crud.yaml"),
            "backend",
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
            "build",
            str(INVALID_DIR / "abstract-entity-in-repo.yaml"),
            "backend",
            "--output",
            output,
        ],
    )
    assert result.exit_code == 1


def test_frontend_honors_cli_output_and_omits_inert_context_actions(tmp_path):
    output = tmp_path / "frontend"
    result = CliRunner().invoke(cli, [
        "build",
        str(V03_EXAMPLES / "crud-pagination" / "spec.yaml"),
        "frontend",
        "--output",
        str(output),
    ])

    assert result.exit_code == 0, result.output
    page = (output / "src" / "pages" / "Articles.tsx").read_text()
    app = (output / "src" / "__generated__" / "App.tsx").read_text()
    assert all(action in page for action in ("Open", "Edit", "Copy IDs", "Delete"))
    assert all(action not in page for action in (
        "Duplicate", "Change status", "Assign to", "Add tag", "Export", "Archive"
    ))
    assert "useEffect" not in app
    assert "const { logout } = useAuth()" not in app


def test_frontend_uses_spec_output_without_cli_override(tmp_path):
    output = tmp_path / "configured-frontend"
    source = (V03_EXAMPLES / "crud-pagination" / "spec.yaml").read_text()
    spec = tmp_path / "spec.yaml"
    spec.write_text(source.replace("./frontend-output", str(output)))

    result = CliRunner().invoke(cli, ["build", str(spec), "frontend"])

    assert result.exit_code == 0, result.output
    assert (output / "src" / "pages" / "Articles.tsx").exists()


def test_frontend_without_ui_block_exits1():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "build",
            str(VALID_DIR / "basic-crud.yaml"),
            "frontend",
        ],
    )
    assert result.exit_code == 1
