"""Each deploy environment is an inventory group whose values the app role renders on its host."""

from yaml_api_generator.ir import IRDeployEnvironment

from .support.deploy import ansible_syntax_check, docker_bundle

ENVIRONMENTS = (
    IRDeployEnvironment(name="staging", env={"BIND_ADDRESS": "127.0.0.1", "APP_PORT": "8001"}, secrets=("S3_KEY",)),
    IRDeployEnvironment(name="production", env={"APP_PORT": "8000"}),
)


def test_without_environments_the_cli_target_is_the_default_group(tmp_path):
    bundle = docker_bundle(tmp_path, name="shop")
    hosts = bundle.load("inventory.yml")["all"]["children"]["default"]["hosts"]
    assert hosts == {
        "shop": {"ansible_host": "localhost", "ansible_user": "ubuntu", "ansible_ssh_private_key_file": "~/.ssh/id_rsa"}
    }
    assert bundle.load("playbook.yml")[0]["hosts"] == "default"
    assert bundle.load("group_vars/default.yml") == {"app_project": "shop"}


def test_environments_are_groups_whose_host_comes_from_the_controller(tmp_path):
    bundle = docker_bundle(tmp_path, name="shop", environments=ENVIRONMENTS)
    groups = bundle.load("inventory.yml")["all"]["children"]
    assert list(groups) == ["staging", "production"]
    host = groups["staging"]["hosts"]["shop-staging"]
    assert host["ansible_host"] == "{{ lookup('ansible.builtin.env', 'DEPLOY_HOST') }}"
    assert "DEPLOY_SSH_PORT" in host["ansible_port"]
    assert bundle.load("playbook.yml")[0]["hosts"] == "{{ deploy_environment }}"


def test_group_vars_hold_literal_env_and_secret_lookups(tmp_path):
    bundle = docker_bundle(tmp_path, name="shop", environments=ENVIRONMENTS)
    assert bundle.load("group_vars/staging.yml") == {
        "app_project": "shop-staging",
        "app_env": {"BIND_ADDRESS": "127.0.0.1", "APP_PORT": "8001"},
        "app_secrets": {"S3_KEY": "{{ lookup('ansible.builtin.env', 'S3_KEY') }}"},
    }
    assert bundle.load("group_vars/production.yml") == {"app_project": "shop-production", "app_env": {"APP_PORT": "8000"}}


def test_generated_secrets_are_kept_on_the_host_not_in_defaults(tmp_path):
    defaults = docker_bundle(tmp_path, environments=ENVIRONMENTS).load("roles/app/defaults/main.yml")
    assert "JWT_SECRET" in defaults["app_generated_secrets"]
    assert not set(defaults["app_defaults"]) & set(defaults["app_generated_secrets"])
    assert (defaults["app_env"], defaults["app_secrets"]) == ({}, {})


def test_release_rolls_back_and_prunes(tmp_path):
    bundle = docker_bundle(tmp_path, environments=ENVIRONMENTS)
    release = bundle.load("roles/app/tasks/release.yml")[0]
    assert release["rescue"][0]["when"] == "previous_tag not in ['', image_tag]"
    assert bundle.load("roles/app/defaults/main.yml")["app_retain"] == 3
    assert "docker_image_remove" in bundle.read("roles/app/tasks/retention.yml")


def test_bundle_ships_ansible_config_and_collections(tmp_path):
    bundle = docker_bundle(tmp_path, environments=ENVIRONMENTS)
    assert "inventory = inventory.yml" in bundle.read("ansible.cfg")
    assert [c["name"] for c in bundle.load("requirements.yml")["collections"]] == ["community.docker", "ansible.posix"]


def test_playbook_passes_ansible_syntax_check(tmp_path):
    ansible_syntax_check(docker_bundle(tmp_path, environments=ENVIRONMENTS), "deploy_environment=staging")
