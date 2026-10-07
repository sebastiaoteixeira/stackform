"""Cross-key rules of the v0.3 ``deploy:`` section, one test per rule."""

import pytest
import yaml

from yaml_api_generator.ir import IRDeployDocker, IRDeployEnvironment, IRDeployFrontend, IRDeployProcess
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

_API = {
    "api": {"basePath": "/api", "version": "v1"},
    "entities": {"note": {"fields": {"id": {"type": "id"}, "title": {"type": "string"}}}},
    "repositories": {"notes": {"entity": "note"}},
    "services": {"notes": {"repository": "notes"}},
    "controllers": {"notes": {"base_path": "/notes", "service": "notes", "access": "public"}},
}


def _write(tmp_path, deploy, version="0.3", **sections):
    spec = tmp_path / "spec.yaml"
    spec.write_text(yaml.safe_dump({"version": version, **_API, **sections, "deploy": {"runtime": "docker", **deploy}}))
    return spec


def _codes(tmp_path, deploy, **sections):
    with pytest.raises(ConfigErrors) as raised:
        load_and_generate_ir(_write(tmp_path, deploy, **sections))
    return [(error.code, error.path) for error in raised.value.errors]


@pytest.fixture
def extensions(tmp_path):
    (tmp_path / "extensions").mkdir()
    return "extensions"


@pytest.fixture
def web(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text("{}")
    return "web"


def test_registry_requires_docker_runtime(tmp_path):
    assert _codes(tmp_path, {"runtime": "systemd", "docker": {"registry": "ghcr.io/acme/app"}}) == [
        ("DEPLOY_DOCKER_ONLY", "deploy.docker.registry"),
    ]


def test_frontend_source_requires_docker_runtime(tmp_path, web):
    assert _codes(tmp_path, {"runtime": "systemd", "frontend": {"source": web}}) == [
        ("DEPLOY_DOCKER_ONLY", "deploy.frontend.source"),
    ]


def test_image_and_registry_are_exclusive(tmp_path):
    docker = {"image": "python:3.12-slim", "registry": "ghcr.io/acme/app"}
    assert _codes(tmp_path, {"docker": docker}) == [("DEPLOY_IMAGE_REGISTRY_EXCLUSIVE", "deploy.docker")]


def test_environments_shipping_built_images_need_registry(tmp_path, extensions):
    deploy = {"backend": {"packages": [extensions]}, "environments": {"staging": {}}}
    assert _codes(tmp_path, deploy) == [("DEPLOY_REGISTRY_REQUIRED", "deploy.docker.registry")]


def test_ssh_delivery_needs_no_registry(tmp_path, extensions):
    deploy = {"docker": {"delivery": "ssh"}, "backend": {"packages": [extensions]}, "environments": {"staging": {}}}
    assert load_and_generate_ir(_write(tmp_path, deploy)).ir.deploy.docker.delivery == "ssh"


@pytest.mark.parametrize("package", [".", "..", "../elsewhere"])
def test_package_must_lie_below_spec(tmp_path, package):
    assert _codes(tmp_path, {"backend": {"packages": [package]}}) == [
        ("DEPLOY_PACKAGE_OUTSIDE_SPEC", "deploy.backend.packages[0]"),
    ]


def test_package_must_exist(tmp_path):
    assert _codes(tmp_path, {"backend": {"packages": ["missing"]}}) == [
        ("DEPLOY_PACKAGE_NOT_FOUND", "deploy.backend.packages[0]"),
    ]


@pytest.mark.parametrize("name", ["app", "my-extensions", "class"])
def test_package_name_must_be_importable(tmp_path, name):
    (tmp_path / name).mkdir()
    assert _codes(tmp_path, {"backend": {"packages": [name]}}) == [
        ("DEPLOY_PACKAGE_NAME_INVALID", "deploy.backend.packages[0]"),
    ]


def test_package_names_are_unique(tmp_path):
    (tmp_path / "a" / "extensions").mkdir(parents=True)
    (tmp_path / "b" / "extensions").mkdir(parents=True)
    assert _codes(tmp_path, {"backend": {"packages": ["a/extensions", "b/extensions"]}}) == [
        ("DEPLOY_PACKAGE_DUPLICATE", "deploy.backend.packages[0]"),
        ("DEPLOY_PACKAGE_DUPLICATE", "deploy.backend.packages[1]"),
    ]


def test_process_declares_exactly_one_of_asgi_or_command(tmp_path):
    processes = {"api": {"asgi": "app:app", "command": "python -m app"}}
    assert [code for code, _ in _codes(tmp_path, {"backend": {"processes": processes}})] == [
        "SCHEMA_VALIDATION_ERROR",
    ]


@pytest.mark.parametrize("processes, found", [
    ({"worker": {"command": "python -m app.worker"}}, 0),
    ({"api": {"asgi": "app:app"}, "admin": {"asgi": "app:admin"}}, 2),
])
def test_exactly_one_asgi_process(tmp_path, processes, found):
    assert _codes(tmp_path, {"backend": {"processes": processes}}) == [
        ("DEPLOY_ASGI_PROCESS_COUNT", "deploy.backend.processes"),
    ]


def test_asgi_module_must_be_generated_or_staged(tmp_path):
    assert _codes(tmp_path, {"backend": {"processes": {"api": {"asgi": "extensions.main:app"}}}}) == [
        ("DEPLOY_ASGI_MODULE_UNKNOWN", "deploy.backend.processes.api.asgi"),
    ]


@pytest.mark.parametrize("name", ["frontend", "mailpit"])
def test_process_names_do_not_clash_with_services(tmp_path, name):
    deploy = {
        "services": {"mailpit": {"image": "axllent/mailpit:latest"}},
        "backend": {"processes": {"api": {"asgi": "app:app"}, name: {"command": "python -m app.worker"}}},
    }
    assert _codes(tmp_path, deploy) == [("DEPLOY_PROCESS_NAME_CLASH", f"deploy.backend.processes.{name}")]


def test_frontend_source_must_lie_below_spec(tmp_path):
    assert _codes(tmp_path, {"frontend": {"source": ".."}}) == [
        ("DEPLOY_FRONTEND_OUTSIDE_SPEC", "deploy.frontend.source"),
    ]


def test_frontend_source_needs_package_json(tmp_path):
    (tmp_path / "web").mkdir()
    assert _codes(tmp_path, {"frontend": {"source": "web"}}) == [
        ("DEPLOY_FRONTEND_NOT_FOUND", "deploy.frontend.source"),
    ]


def test_frontend_names_are_disjoint(tmp_path, web):
    frontend = {"source": web, "env": ["VITE_API_BASE_URL"], "secrets": ["VITE_API_BASE_URL"]}
    assert _codes(tmp_path, {"frontend": frontend}) == [
        ("DEPLOY_FRONTEND_NAME_OVERLAP", "deploy.frontend.secrets"),
    ]


def test_frontend_names_are_env_names(tmp_path, web):
    assert [code for code, _ in _codes(tmp_path, {"frontend": {"source": web, "env": ["api-url"]}})] == [
        "SCHEMA_VALIDATION_ERROR",
    ]


def test_environment_name_is_lowercase(tmp_path):
    assert [code for code, _ in _codes(tmp_path, {"environments": {"Staging": {}}})] == [
        "SCHEMA_VALIDATION_ERROR",
    ]


def test_environment_values_are_literal(tmp_path):
    environments = {"staging": {"env": {"APP_PORT": "$\\{PORT\\}"}}}
    assert _codes(tmp_path, {"environments": environments}) == [
        ("DEPLOY_ENV_VALUE_INTERPOLATED", "deploy.environments.staging.env.APP_PORT"),
    ]


@pytest.mark.parametrize("value", ["{{ lookup('env', 'HOME') }}", "{% raw %}", "{# note #}"])
def test_environment_values_are_not_templates(tmp_path, value):
    assert _codes(tmp_path, {"environments": {"staging": {"env": {"GREETING": value}}}}) == [
        ("DEPLOY_ENV_VALUE_INTERPOLATED", "deploy.environments.staging.env.GREETING"),
    ]


def test_frontend_source_excludes_generated_ui(tmp_path, web):
    assert _codes(tmp_path, {"frontend": {"source": web}}, ui={"frontend": {"pack": "default"}}) == [
        ("DEPLOY_FRONTEND_SOURCE_WITH_UI", "deploy.frontend.source"),
    ]


def test_frontend_env_is_never_a_secret(tmp_path, web):
    deploy = {
        "frontend": {"source": web, "env": ["API_URL"]},
        "environments": {"staging": {"secrets": ["API_URL"]}},
        "docker": {"delivery": "ssh"},
    }
    assert _codes(tmp_path, deploy) == [("DEPLOY_FRONTEND_ENV_SECRET", "deploy.environments.staging.secrets")]


def test_environment_env_and_secrets_are_disjoint(tmp_path):
    environments = {"staging": {"env": {"S3_ACCESS_KEY": "x"}, "secrets": ["S3_ACCESS_KEY"]}}
    assert _codes(tmp_path, {"environments": environments}) == [
        ("DEPLOY_ENV_SECRET_OVERLAP", "deploy.environments.staging.secrets"),
    ]


def test_v02_warns_on_v03_deploy_keys(tmp_path):
    spec = _write(tmp_path, {"docker": {"registry": "ghcr.io/acme/app"}, "environments": {}}, version="0.2")
    result = load_and_generate_ir(spec)
    assert [(w.code, w.path) for w in result.warnings if w.code == "DEPLOY_KEY_IGNORED"] == [
        ("DEPLOY_KEY_IGNORED", "deploy.docker.registry"),
        ("DEPLOY_KEY_IGNORED", "deploy.environments"),
    ]
    assert result.ir.deploy.docker == IRDeployDocker()


def test_full_deploy_spec_builds_ir(tmp_path, extensions, web):
    deploy = {
        "name": "shop",
        "docker": {"registry": "ghcr.io/acme/app", "retain": 5},
        "backend": {
            "packages": [extensions],
            "system_packages": ["libpq5"],
            "processes": {
                "api": {"asgi": "extensions.main:app"},
                "worker": {"command": ["python", "-m", "extensions.worker"], "env": {"QUEUE": "default"}},
            },
        },
        "frontend": {"source": web, "env": ["VITE_API_BASE_URL"], "secrets": ["NPM_TOKEN"]},
        "environments": {"staging": {"env": {"APP_PORT": "8001"}, "secrets": ["S3_SECRET_KEY"]}},
    }
    ir = load_and_generate_ir(_write(tmp_path, deploy)).ir.deploy
    assert ir.docker == IRDeployDocker(registry="ghcr.io/acme/app", delivery="registry", retain=5)
    assert ir.backend.packages == ("extensions",)
    assert ir.backend.processes == (
        IRDeployProcess(name="api", asgi="extensions.main:app"),
        IRDeployProcess(name="worker", command=("python", "-m", "extensions.worker"), env={"QUEUE": "default"}),
    )
    assert ir.frontend == IRDeployFrontend(source="web", env=("VITE_API_BASE_URL",), secrets=("NPM_TOKEN",))
    assert ir.environments == (
        IRDeployEnvironment(name="staging", env={"APP_PORT": "8001"}, secrets=("S3_SECRET_KEY",)),
    )


def test_default_backend_serves_generated_app(tmp_path):
    ir = load_and_generate_ir(_write(tmp_path, {})).ir.deploy
    assert ir.backend.processes == (IRDeployProcess(name="app", asgi="app:app"),)
    assert ir.frontend.source is None
    assert ir.environments == ()


def test_process_dependency_requires_docker(tmp_path):
    deploy = {"runtime": "systemd", "backend": {"processes": {
        "api": {"asgi": "app:app", "depends_on": {"setup": "service_completed_successfully"}},
    }}}
    assert _codes(tmp_path, deploy) == [("DEPLOY_DOCKER_ONLY", "deploy.backend.processes.api.depends_on")]
