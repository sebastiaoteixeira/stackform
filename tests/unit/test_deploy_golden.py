"""A spec without the deploy extension keys keeps generating the same bundle on each runtime."""

from pathlib import Path

import pytest

from tests.conftest import FIXTURES_DIR
from yaml_api_generator.generators.deploy.generate import generate_deploy
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

from .support.deploy import DeployBundle, compose_config

EXAMPLES_DIR = Path(__file__).parents[2] / "examples" / "valid"


def _files(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): path.read_text() for path in sorted(root.rglob("*")) if path.is_file()}


def _bundle(tmp_path, runtime: str) -> DeployBundle:
    spec = EXAMPLES_DIR / f"deploy-{runtime}.yaml"
    generate_deploy(load_and_generate_ir(str(spec)).ir, str(tmp_path), spec.parent)
    return DeployBundle(tmp_path)


@pytest.mark.parametrize("runtime", ["docker", "systemd"])
def test_bundle_matches_golden(tmp_path, runtime):
    assert _files(_bundle(tmp_path, runtime).root) == _files(FIXTURES_DIR / "golden" / f"deploy-{runtime}")


def test_compose_resolves_single_app_service(tmp_path):
    services = compose_config(_bundle(tmp_path, "docker"))["services"]
    assert list(services) == ["app"]
    assert services["app"]["image"] == "python:3.11-slim"
    assert services["app"]["ports"][0]["target"] == 8080
