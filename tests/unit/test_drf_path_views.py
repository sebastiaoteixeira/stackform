"""The generated DRF backend serves each path from its own view, so routes sharing a collection keep their own access."""

import ast
import re

import pytest

from tests.unit.support.live_apps import mongo, write_spec
from tests.unit.test_identity_http import _SPEC
from yaml_api_generator.cli.compiler import compile_project


@pytest.fixture(scope="module")
def backend(tmp_path_factory):
    directory = tmp_path_factory.mktemp("drf")
    compile_project(yaml_file=write_spec(directory, _SPEC, mongo("mongodb://localhost", "drf")), output_dir=directory / "generated", target="drf")
    return directory / "generated" / "backend" / "api"


def _patterns(backend):
    return re.findall(r'path\("([^"]*)", (\w+)\.as_view\(\)', (backend / "urls.py").read_text())


def _grants(backend, view):
    """The ``assignable`` flag of every role grant in ``view`` of the users module."""
    module = ast.parse((backend / "views" / "users.py").read_text())
    cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == view)
    return [
        keyword.value.value
        for call in ast.walk(cls)
        if isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "granted"
        for keyword in call.keywords
    ]


def test_every_path_has_its_own_view(backend):
    patterns = _patterns(backend)

    assert len({view for _, view in patterns}) == len(patterns)


def test_literal_paths_precede_parameterised_siblings(backend):
    paths = [path for path, _ in _patterns(backend)]

    assert paths.index("users/register") < paths.index("users/<str:id>")


def test_register_grants_the_default_and_authenticated_create_the_requested_role(backend):
    assert (_grants(backend, "View_users_register"), _grants(backend, "View_users")) == ([False], [True])


def test_disabled_login_serves_no_login_route(backend):
    assert not any(path.endswith("/login") for path, _ in _patterns(backend))
