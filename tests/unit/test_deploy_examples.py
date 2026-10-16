"""The deploy examples: the extension example builds its bundle, each invalid one fails on its rule."""

from pathlib import Path

import pytest

from yaml_api_generator.generators.deploy.generate import generate_deploy
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

from .support.deploy import DeployBundle, compose_config

EXAMPLES_DIR = Path(__file__).parents[2] / "examples"
EXTENSION = EXAMPLES_DIR / "valid" / "deploy-extension.yaml"


@pytest.fixture
def bundle(tmp_path) -> DeployBundle:
    generate_deploy(load_and_generate_ir(str(EXTENSION)).ir, str(tmp_path), EXTENSION.parent)
    return DeployBundle(tmp_path)


def test_extension_bundle_runs_processes_frontend_and_services(bundle):
    assert list(bundle.services) == ["api", "worker", "postgres", "frontend", "mailpit"]
    assert bundle.services["worker"]["image"] == "ghcr.io/example/shop/backend:${IMAGE_TAG:-latest}"
    assert (bundle.root / "packages/extensions/requirements.txt").is_file()
    assert (bundle.root / "frontend/package.json").is_file()
    assert sorted(path.name for path in (bundle.root / "group_vars").iterdir()) == ["production.yml", "staging.yml"]


def test_extension_compose_resolves(bundle):
    services = compose_config(bundle)["services"]
    assert services["api"]["build"]["additional_contexts"] == {"extensions": str(bundle.root / "packages/extensions")}
    assert services["worker"]["command"] == ["python", "-m", "extensions.worker"]


@pytest.mark.parametrize(
    ("example", "code"),
    [
        ("deploy-image-and-registry", "DEPLOY_IMAGE_REGISTRY_EXCLUSIVE"),
        ("deploy-two-asgi-processes", "DEPLOY_ASGI_PROCESS_COUNT"),
        ("deploy-registry-on-systemd", "DEPLOY_DOCKER_ONLY"),
        ("deploy-package-outside-spec", "DEPLOY_PACKAGE_OUTSIDE_SPEC"),
        ("deploy-env-secret-overlap", "DEPLOY_ENV_SECRET_OVERLAP"),
    ],
)
def test_invalid_example_fails_on_its_rule(example, code):
    with pytest.raises(ConfigErrors) as raised:
        load_and_generate_ir(str(EXAMPLES_DIR / "invalid" / f"{example}.yaml"))
    assert [error.code for error in raised.value.errors] == [code]
