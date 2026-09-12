import compileall
from pathlib import Path

import pytest

from yaml_api_generator.cli.compiler import compile_project


_EXAMPLES = Path(__file__).parents[2] / "examples" / "v03"


@pytest.mark.parametrize(
    ("example", "target"),
    [
        ("crud-pagination", "fastapi"),
        ("access-bindings", "fastapi"),
        ("access-bindings", "drf"),
        ("access-bindings", "raw"),
        ("secure-session", "fastapi"),
        ("oidc-pkce-dpop", "fastapi"),
        ("mongo-migrations", "fastapi"),
        ("mongo-migrations", "drf"),
        ("mongo-migrations", "raw"),
    ],
)
def test_v03_example_builds_for_documented_target(tmp_path, example, target):
    compile_project(
        yaml_file=str(_EXAMPLES / example / "spec.yaml"),
        output_dir=str(tmp_path / example / target),
        target=target,
    )

    backend = tmp_path / example / target / "backend"
    assert compileall.compile_dir(str(backend), quiet=2)
