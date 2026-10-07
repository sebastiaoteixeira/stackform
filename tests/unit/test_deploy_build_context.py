"""Build contexts of deploy services are staged into the generated bundle."""
import pytest

from yaml_api_generator.generators.deploy.context import DeployTarget, DockerDeployContext
from yaml_api_generator.generators.deploy.docker.generator import DockerDeployGenerator


def _ctx(extra_services):
    return DockerDeployContext(
        name="app",
        port=8000,
        runtime="docker",
        mongo_local=False,
        mongo_db="testdb",
        env_vars={},
        has_auth=False,
        target=DeployTarget(),
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


def test_readme_documents_ansible_vault_hardening(tmp_path):
    """The generated deploy README documents the opt-in ansible-vault path."""
    out = tmp_path / "out"
    DockerDeployGenerator().generate(_ctx(()), out, tmp_path)
    readme = (out / "README.md").read_text()
    assert "Hardening: encrypt secrets at rest with ansible-vault" in readme
    assert "group_vars/all/secrets.yml" in readme
    assert "ansible-vault encrypt group_vars/all/secrets.yml" in readme
    assert "--ask-vault-pass" in readme
    assert "--vault-password-file" in readme


def test_required_secrets_are_added_to_env_vars(tmp_path):
    """JWT_SECRET and other backend secrets must surface in deploy secret_env_names."""
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
    ctx = build_deploy_context(ir, tmp_path)
    assert "JWT_SECRET" in ctx.secret_env_names
    assert "KEYCLOAK_CLIENT_SECRET" in ctx.secret_env_names
    assert ctx.env_vars["JWT_SECRET"] == ""
    assert ctx.env_vars["KEYCLOAK_CLIENT_SECRET"] == ""


def test_secrets_required_passthrough_in_app_environment(tmp_path):
    """Secrets use required passthrough ${VAR} in compose — no plaintext default baked in."""
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
    ctx = build_deploy_context(ir, tmp_path)
    assert "JWT_SECRET=${JWT_SECRET}" in ctx.app_environment
    assert "KEYCLOAK_CLIENT_SECRET=${KEYCLOAK_CLIENT_SECRET}" in ctx.app_environment
    assert not any(":-" in v for v in ctx.app_environment if "JWT_SECRET" in v)


def test_ansible_role_generates_secrets_and_renders_env(tmp_path):
    """The Ansible app role must generate secrets via password lookup and template .env on remote."""
    from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
    from yaml_api_generator.generators.deploy.context_builder import build_deploy_context
    from yaml_api_generator.generators.deploy.docker.generator import DockerDeployGenerator
    from tests.conftest import VALID_DIR

    spec = tmp_path / "spec.yaml"
    spec.write_text((VALID_DIR / "auth-oidc.yaml").read_text() + """
deploy:
  runtime: docker
  name: app
  port: 8000
""")
    ir = load_and_generate_ir(str(spec)).ir
    ctx = build_deploy_context(ir, tmp_path)
    out = tmp_path / "out"
    DockerDeployGenerator().generate(ctx, out, tmp_path)

    tasks = (out / "roles" / "app" / "tasks" / "environment.yml").read_text()
    assert "lookup('ansible.builtin.password'" in tasks
    release = (out / "roles" / "app" / "tasks" / "release.yml").read_text()
    assert "ansible.builtin.template:" in release
    assert "env.j2" in release

    assert not (out / ".env").exists()
    assert (out / "roles" / "app" / "templates" / "env.j2").exists()


@pytest.mark.parametrize("context", [".", "..", "./out"])
def test_build_context_enclosing_spec_or_output_rejected(tmp_path, context):
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    out = spec_dir / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="must be a subdirectory"):
        _generate(_ctx((("frontend", {"build": {"context": context}}),)), spec_dir, out)
    assert list(out.iterdir()) == []
