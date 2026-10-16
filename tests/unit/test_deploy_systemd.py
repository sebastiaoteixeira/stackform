"""The systemd bundle runs one unit per backend process from a virtualenv that holds the packages."""

from jinja2 import Environment, FileSystemLoader

from yaml_api_generator.ir import IRDeployBackend, IRDeployEnvironment, IRDeployProcess

from .support.deploy import DeployBundle, ansible_syntax_check, deploy_bundle

_PROCESSES = (
    IRDeployProcess(name="api", asgi="extensions.main:app"),
    IRDeployProcess(name="worker", command=("python", "-m", "extensions.worker", "--queue", "high priority"), env={"QUEUE": "high"}),
    IRDeployProcess(name="beat", command="python -m extensions.beat"),
)

ENVIRONMENTS = (
    IRDeployEnvironment(name="staging", env={"LOG_LEVEL": "debug"}, secrets=("S3_KEY",)),
    IRDeployEnvironment(name="production"),
)


def _bundle(tmp_path, **deploy) -> DeployBundle:
    for path in ("extensions/requirements.txt", "extensions/jobs/requirements.txt"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("")
    backend = IRDeployBackend(packages=("extensions",), system_packages=("libpq5",), processes=_PROCESSES)
    return deploy_bundle(tmp_path, runtime="systemd", name="shop", backend=backend, **deploy)


def _unit(bundle: DeployBundle, unit: dict, **variables) -> str:
    """The unit file Ansible renders on the host for ``unit``."""
    env = Environment(loader=FileSystemLoader(bundle.root / "roles/app/templates"), keep_trailing_newline=True,
                      trim_blocks=True, lstrip_blocks=True)
    env.filters.update(bundle.filters)
    return env.get_template("unit.service.j2").render(item=unit, **variables)


def test_one_unit_per_process(tmp_path):
    units = _bundle(tmp_path).load("roles/app/defaults/main.yml")["app_units"]
    assert units == [
        {"name": "{{ app_project }}-api", "command": "uvicorn extensions.main:app --host 0.0.0.0 --port 8000", "env": {}},
        {
            "name": "{{ app_project }}-worker",
            "command": "python -m extensions.worker --queue 'high priority'",
            "env": {"QUEUE": "high"},
        },
        {"name": "{{ app_project }}-beat", "command": "python -m extensions.beat", "env": {}},
    ]


def test_generated_app_keeps_its_unit(tmp_path):
    defaults = deploy_bundle(tmp_path, runtime="systemd", name="shop").load("roles/app/defaults/main.yml")
    assert [unit["name"] for unit in defaults["app_units"]] == ["{{ app_project }}"]
    assert (defaults["app_packages"], defaults["app_requirements"]) == ([], ["requirements.txt"])


def test_packages_synced_with_their_requirements(tmp_path):
    bundle = _bundle(tmp_path)
    defaults = bundle.load("roles/app/defaults/main.yml")
    assert defaults["app_packages"] == ["extensions"]
    assert defaults["app_system_packages"] == ["libpq5"]
    assert defaults["app_requirements"] == [
        "requirements.txt", "packages/extensions/jobs/requirements.txt", "packages/extensions/requirements.txt",
    ]
    assert (bundle.root / "packages/extensions/requirements.txt").is_file()


def test_unit_runs_the_command_from_the_virtualenv(tmp_path):
    bundle = _bundle(tmp_path)
    worker = bundle.load("roles/app/defaults/main.yml")["app_units"][1]
    unit = _unit(
        bundle, {**worker, "name": "shop-worker"},
        app_dir="/opt/shop", app_user="www-data", app_restart="always", app_packages=["extensions"],
    )
    assert "ExecStart=/usr/bin/env python -m extensions.worker --queue 'high priority'\n" in unit
    assert 'Environment="PATH=/opt/shop/venv/bin:/usr/local/bin:/usr/bin:/bin"' in unit
    assert 'Environment="PYTHONPATH=/opt/shop/packages"' in unit
    assert 'Environment="QUEUE=high"' in unit
    assert "EnvironmentFile=/opt/shop/.env" in unit


def test_empty_defaults_never_mask_the_app_defaults(tmp_path):
    defaults = _bundle(tmp_path).load("roles/app/defaults/main.yml")
    assert all(defaults["app_defaults"].values())
    assert "JWT_SECRET" in defaults["app_generated_secrets"]


def test_environments_are_groups_with_their_own_project(tmp_path):
    bundle = _bundle(tmp_path, environments=ENVIRONMENTS)
    groups = bundle.load("inventory.yml")["all"]["children"]
    assert {name: list(group["hosts"]) for name, group in groups.items()} == {
        "staging": ["shop-staging"], "production": ["shop-production"],
    }
    assert bundle.load("playbook.yml")[-1]["hosts"] == "{{ deploy_environment }}"
    assert bundle.load("group_vars/staging.yml") == {
        "app_project": "shop-staging",
        "app_env": {"LOG_LEVEL": "debug"},
        "app_secrets": {"S3_KEY": "{{ lookup('ansible.builtin.env', 'S3_KEY') }}"},
    }


def test_bundle_ships_the_shared_release_environment(tmp_path):
    bundle = _bundle(tmp_path)
    assert "import_tasks: environment.yml" in bundle.read("roles/app/tasks/main.yml")
    assert (bundle.root / "roles/app/templates/env.j2").is_file()
    assert [c["name"] for c in bundle.load("requirements.yml")["collections"]] == ["ansible.posix"]
    (env_file,) = (task for task in bundle.load("roles/app/tasks/main.yml") if task.get("ansible.builtin.template", {}).get("src") == "env.j2")
    assert env_file["ansible.builtin.template"]["owner"] == "{{ app_user }}"


def test_unit_values_reach_systemd_literally(tmp_path):
    unit = _unit(
        _bundle(tmp_path), {"name": "shop-report", "command": "date +%Y", "env": {"GREETING": '50% "off"'}},
        app_dir="/opt/shop", app_user="www-data", app_restart="always", app_packages=[],
    )
    assert "ExecStart=/usr/bin/env date +%%Y\n" in unit
    assert 'Environment="GREETING=50%% \\"off\\""' in unit


def test_playbook_passes_ansible_syntax_check(tmp_path):
    ansible_syntax_check(_bundle(tmp_path, environments=ENVIRONMENTS), "deploy_environment=staging")
