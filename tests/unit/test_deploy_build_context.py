"""Build contexts of deploy services are staged into the generated bundle."""
import pytest

from yaml_api_generator.generators.deploy.context import DockerDeployContext
from yaml_api_generator.generators.deploy.docker.generator import DockerDeployGenerator


def _ctx(extra_services):
    return DockerDeployContext(
        name="app",
        port=8000,
        runtime="docker",
        mongo_local=False,
        mongo_db="testdb",
        env_vars=[],
        has_auth=False,
        has_frontend=False,
        host="localhost",
        ssh_user="ubuntu",
        ssh_key="~/.ssh/id_rsa",
        datastores=(),
        extra_services=extra_services,
    )


def _generate(ctx, spec_dir, output_dir):
    DockerDeployGenerator().generate(ctx, output_dir, spec_dir)
    return (output_dir / "docker-compose.yml").read_text()


def test_build_context_copied_into_bundle(tmp_path):
    spec_dir = tmp_path / "spec"
    (spec_dir / "frontend").mkdir(parents=True)
    (spec_dir / "frontend" / "Dockerfile").write_text("FROM nginx\n")
    out = tmp_path / "out"

    compose = _generate(
        _ctx((("frontend", {"build": {"context": "./frontend"}, "ports": ["3000:80"]}),)),
        spec_dir,
        out,
    )

    assert (out / "frontend" / "Dockerfile").is_file()
    assert "context: ./frontend" in compose


def test_string_build_shorthand_copied(tmp_path):
    spec_dir = tmp_path / "spec"
    (spec_dir / "worker").mkdir(parents=True)
    (spec_dir / "worker" / "Dockerfile").write_text("FROM python\n")
    out = tmp_path / "out"

    _generate(_ctx((("worker", {"build": "./worker"}),)), spec_dir, out)

    assert (out / "worker" / "Dockerfile").is_file()


def test_missing_build_context_raises(tmp_path):
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="build context not found"):
        _generate(_ctx((("frontend", {"build": {"context": "./nope"}}),)), tmp_path, out)


def test_image_service_untouched(tmp_path):
    out = tmp_path / "out"
    compose = _generate(_ctx((("cache", {"image": "redis:7"}),)), tmp_path, out)
    assert "image: redis:7" in compose


def test_required_secrets_are_added_to_env_vars(tmp_path):
    """JWT_SECRET and other backend secrets must surface in deploy env vars."""
    from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
    from yaml_api_generator.generators.deploy.context_builder import build_deploy_context
    from tests.conftest import VALID_DIR

    spec = tmp_path / "spec.yaml"
    spec.write_text((VALID_DIR / "auth-oidc.yaml").read_text() + """
deploy:
  runtime: docker
  name: app
  port: 8000
""")
    ir = load_and_generate_ir(str(spec)).ir
    ctx = build_deploy_context(ir, "localhost", "ubuntu", "~/.ssh/id_rsa")
    assert "JWT_SECRET" in ctx.env_vars
    assert "KEYCLOAK_CLIENT_SECRET" in ctx.env_vars


def test_required_secrets_passthrough_in_app_environment(tmp_path):
    """Required secrets are passed through to the app container, failing fast if unset."""
    from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
    from yaml_api_generator.generators.deploy.context_builder import build_deploy_context
    from tests.conftest import VALID_DIR

    spec = tmp_path / "spec.yaml"
    spec.write_text((VALID_DIR / "auth-oidc.yaml").read_text() + """
deploy:
  runtime: docker
  name: app
  port: 8000
""")
    ir = load_and_generate_ir(str(spec)).ir
    ctx = build_deploy_context(ir, "localhost", "ubuntu", "~/.ssh/id_rsa")
    assert "JWT_SECRET=${JWT_SECRET:?JWT_SECRET is required}" in ctx.app_environment
    assert "KEYCLOAK_CLIENT_SECRET=${KEYCLOAK_CLIENT_SECRET:?KEYCLOAK_CLIENT_SECRET is required}" in ctx.app_environment
