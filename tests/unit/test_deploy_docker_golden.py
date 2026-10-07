"""A spec without the deploy extension keys keeps generating the same docker bundle."""

from pathlib import Path

from tests.conftest import FIXTURES_DIR
from yaml_api_generator.generators.deploy.generate import generate_deploy
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

from .support.deploy import DockerBundle, compose_config

SPEC = Path(__file__).parents[2] / "examples" / "valid" / "deploy-docker.yaml"
GOLDEN = FIXTURES_DIR / "golden" / "deploy-docker"


def _files(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): path.read_text() for path in sorted(root.rglob("*")) if path.is_file()}


def _bundle(tmp_path) -> DockerBundle:
    generate_deploy(load_and_generate_ir(str(SPEC)).ir, str(tmp_path), SPEC.parent)
    return DockerBundle(tmp_path)


def test_bundle_matches_golden(tmp_path):
    assert _files(_bundle(tmp_path).root) == _files(GOLDEN)


def test_compose_resolves_single_app_service(tmp_path):
    services = compose_config(_bundle(tmp_path))["services"]
    assert list(services) == ["app"]
    assert services["app"]["image"] == "python:3.11-slim"
    assert services["app"]["ports"][0]["target"] == 8080
