import compileall
import os
from pathlib import Path
import subprocess
import sys

import pytest

from yaml_api_generator.cli.compiler import compile_project


EXAMPLES = Path(__file__).parents[2] / "examples"
V01_EXAMPLES = ("auth-api-key", "blog", "auth-users")


@pytest.mark.parametrize("example", V01_EXAMPLES)
@pytest.mark.parametrize("target", ("fastapi", "drf", "raw"))
def test_v01_examples_generate_every_backend(tmp_path, example, target):
    output = tmp_path / example / target

    compile_project(
        EXAMPLES / "valid" / f"{example}.yaml",
        output_dir=output,
        target=target,
    )

    assert compileall.compile_dir(str(output / "backend"), quiet=2)


def test_path_parameter_example_declares_its_route_operations(tmp_path):
    output = tmp_path / "path-parameters"

    compile_project(
        EXAMPLES / "valid" / "path-parameters.yaml",
        output_dir=output,
        target="fastapi",
    )

    routes = (output / "backend" / "routes" / "comments.py").read_text()
    assert "async def by_post_comments" in routes
    assert "async def create_comments" in routes


@pytest.mark.parametrize("example", ("api-with-ui.yaml", "api-with-admin.yaml"))
def test_v02_custom_pack_examples_generate(tmp_path, example):
    output = tmp_path / example

    compile_project(EXAMPLES / "v02" / example, output_dir=output)

    assert compileall.compile_dir(str(output / "backend"), quiet=2)
    assert (output / "frontend" / "package.json").exists()
    assert (output / "frontend" / "src" / "__generated__" / "App.tsx").exists()
    generated_types = (
        output / "frontend" / "src" / "__generated__" / "types" / "index.tsx"
    )
    if generated_types.exists():
        assert ": enum" not in generated_types.read_text()


def test_raw_routes_use_one_prefix_and_include_environment_files(tmp_path):
    output = tmp_path / "raw"
    compile_project(
        EXAMPLES / "valid" / "auth-users.yaml",
        output_dir=output,
        target="raw",
    )
    backend = output / "backend"

    assert (backend / ".env").exists()
    assert (backend / ".env.example").exists()
    assert "JWT_SECRET=<jwt_secret>" in (backend / ".env.example").read_text()

    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            (str(backend), str(Path(__file__).parents[2] / "src"))
        ),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app import app; "
                "print(app._match_route('GET', '/api/v1/users')[0] is not None); "
                "print(app._match_route('GET', '/api/v1/api/v1/users')[0] is not None)"
            ),
        ],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout.splitlines() == ["True", "False"]
