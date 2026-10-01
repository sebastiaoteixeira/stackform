import compileall
import re
from pathlib import Path

import pytest

from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.parsers.errors import ConfigErrors


_EXAMPLES = Path(__file__).parents[2] / "examples" / "v03"

# Jinja renders an undefined template value through repr() as this bare name,
# which byte-compiles cleanly and fails only when the route runs.
_UNDEFINED_SENTINEL = re.compile(r"\bUndefined\b")


@pytest.mark.parametrize(
    ("example", "target"),
    [
        ("crud-pagination", "fastapi"),
        ("password-role", "fastapi"),
        ("access-bindings", "fastapi"),
        ("access-bindings", "drf"),
        ("access-bindings", "raw"),
        ("secure-session", "fastapi"),
        ("oidc-pkce-dpop", "fastapi"),
        ("mongo-migrations", "fastapi"),
        ("mongo-migrations", "drf"),
        ("mongo-migrations", "raw"),
        ("files", "fastapi"),
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
    leaks = [
        str(module.relative_to(backend))
        for module in backend.rglob("*.py")
        if _UNDEFINED_SENTINEL.search(module.read_text())
    ]
    assert leaks == []


@pytest.mark.parametrize("target", ["drf", "raw"])
def test_files_example_is_refused_by_targets_without_file_datastores(tmp_path, target):
    with pytest.raises(ConfigErrors) as raised:
        compile_project(
            yaml_file=str(_EXAMPLES / "files" / "spec.yaml"),
            output_dir=str(tmp_path / target),
            target=target,
        )

    assert [error.code for error in raised.value.errors] == ["BACKEND_FEATURE_UNSUPPORTED"]
