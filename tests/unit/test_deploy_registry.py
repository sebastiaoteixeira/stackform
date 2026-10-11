"""Release images reach the host from a registry, over SSH, or by being built there."""

import pytest

from yaml_api_generator.ir import IRDeployDocker, IRDeployEnvironment, IRDeployFrontend

from .support.deploy import deploy_bundle

ENVIRONMENTS = (IRDeployEnvironment(name="staging"),)


@pytest.fixture
def web(tmp_path) -> IRDeployFrontend:
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text("{}")
    return IRDeployFrontend(source="web")


def _deliveries(bundle) -> list[str]:
    return sorted(path.name for path in (bundle.root / "roles/app/tasks/deliver").iterdir())


def test_registry_delivery_pulls_tagged_images_between_login_and_logout(tmp_path, web):
    bundle = deploy_bundle(
        tmp_path, environments=ENVIRONMENTS, docker=IRDeployDocker(registry="ghcr.io/example/shop"), frontend=web,
    )
    defaults = bundle.load("roles/app/defaults/main.yml")
    assert (defaults["app_delivery"], defaults["app_registry"]) == ("registry", "ghcr.io")
    assert defaults["app_repositories"] == ["ghcr.io/example/shop/backend", "ghcr.io/example/shop/frontend"]
    assert defaults["app_build"] == "never"
    assert "image_tag" not in defaults
    assert _deliveries(bundle) == ["registry.yml"]
    directory, pull = bundle.load("roles/app/tasks/deliver/registry.yml")
    assert directory["ansible.builtin.file"]["path"] == "{{ app_dir }}/.docker"
    assert directory["ansible.builtin.file"]["mode"] == "0700"
    assert pull["environment"] == {"DOCKER_CONFIG": "{{ app_dir }}/.docker"}
    for task in [pull["block"][0], pull["always"][0]]:
        assert task["community.docker.docker_login"]["config_path"] == "{{ app_dir }}/.docker/config.json"
    assert [task["name"] for task in pull["block"]] == ["Log in to the registry", "Pull the release images"]
    assert pull["always"][0]["community.docker.docker_login"]["state"] == "absent"
    assert bundle.services["app"]["image"] == "ghcr.io/example/shop/backend:${IMAGE_TAG:-latest}"


@pytest.mark.parametrize(
    ("registry", "host"),
    [("example/shop", "docker.io"), ("registry.example.com:5000/shop", "registry.example.com:5000"), ("localhost/shop", "localhost")],
)
def test_registry_host_follows_docker_reference_rules(tmp_path, registry, host):
    bundle = deploy_bundle(tmp_path, environments=ENVIRONMENTS, docker=IRDeployDocker(registry=registry))
    assert bundle.load("roles/app/defaults/main.yml")["app_registry"] == host


def test_ssh_delivery_loads_an_image_archive(tmp_path, web):
    bundle = deploy_bundle(
        tmp_path, name="shop", environments=ENVIRONMENTS, docker=IRDeployDocker(delivery="ssh"), frontend=web,
    )
    defaults = bundle.load("roles/app/defaults/main.yml")
    assert defaults["app_delivery"] == "ssh"
    assert defaults["image_archive"] == "{{ playbook_dir }}/images.tar.zst"
    assert defaults["app_repositories"] == ["shop/backend", "shop/frontend"]
    assert "app_registry" not in defaults
    assert _deliveries(bundle) == ["ssh.yml"]
    assert "community.docker.docker_image_load" in bundle.read("roles/app/tasks/deliver/ssh.yml")
    assert "docker save shop/backend:<tag> shop/frontend:<tag> | zstd" in bundle.read("README.md")


def test_without_registry_images_are_built_on_the_host(tmp_path):
    bundle = deploy_bundle(tmp_path)
    defaults = bundle.load("roles/app/defaults/main.yml")
    assert (defaults["app_delivery"], defaults["app_build"], defaults["image_tag"]) == ("host", "always", "latest")
    assert _deliveries(bundle) == ["host.yml"]


def test_pinned_image_is_pulled_and_never_pruned(tmp_path):
    bundle = deploy_bundle(tmp_path, docker=IRDeployDocker(image="python:3.11-slim"))
    defaults = bundle.load("roles/app/defaults/main.yml")
    assert defaults["app_build"] == "never"
    assert bundle.services["app"]["pull_policy"] == "always"
    assert not any(repository.endswith("/backend") for repository in defaults["app_repositories"])


def test_pinned_image_still_builds_the_frontend_on_the_host(tmp_path, web):
    bundle = deploy_bundle(tmp_path, docker=IRDeployDocker(image="python:3.11-slim"), frontend=web)
    assert bundle.load("roles/app/defaults/main.yml")["app_build"] == "always"
    assert bundle.services["app"]["pull_policy"] == "always"
    assert "pull_policy" not in bundle.services["frontend"]
