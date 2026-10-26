"""The generated UI signs in with a password only through an identity that serves a login route, and registers through one that serves register."""

import re

import pytest

from tests.unit.support.live_apps import write_spec
from tests.unit.test_identity_http import _SPEC
from yaml_api_generator.generators.frontend.packs.loader import load_pack
from yaml_api_generator.generators.frontend.renderer import render_templates
from yaml_api_generator.parsers.ui_parser import build_generator_context
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

PASSWORD_FORM = re.compile(r"<Auth\b")
SIGN_IN_CALL = re.compile(r"callOperation\('\w+', '(login|register)'")
LOGIN_VIEW = {"views": {"signIn": {"path": "/login", "component": "auth-tabbed"}}}


def _context(tmp_path, login, ui=None):
    spec = _SPEC.replace("login: false", f"login: {str(login).lower()}")
    ir = load_and_generate_ir(str(write_spec(tmp_path, spec))).ir
    return build_generator_context(ir, ui or {}, load_pack("generic").manifest)


def _app(context):
    files = {item.path: item.content for item in render_templates(load_pack("generic"), context)}
    return files["src/__generated__/App.tsx"]


def test_disabled_login_renders_registration_only(tmp_path):
    app = _app(_context(tmp_path, login=False))

    assert {match.group(1) for match in SIGN_IN_CALL.finditer(app)} == {"register"}
    assert PASSWORD_FORM.search(app)


def test_enabled_login_signs_in_through_the_identity_login_route(tmp_path):
    app = _app(_context(tmp_path, login=True))

    assert {match.group(1) for match in SIGN_IN_CALL.finditer(app)} == {"login", "register"}
    assert PASSWORD_FORM.search(app)


def test_a_login_view_without_a_login_route_aborts_generation(tmp_path):
    with pytest.raises(ValueError, match="no identity serves a login route"):
        _context(tmp_path, login=False, ui=LOGIN_VIEW)
