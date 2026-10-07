"""Every backend process runs as its own compose service of one shared backend image."""

from yaml_api_generator.ir import IRDeployBackend, IRDeployDocker, IRDeployProcess

from .support.deploy import compose_config, deploy_bundle

_PROCESSES = (
    IRDeployProcess(name="api", asgi="extensions.main:app"),
    IRDeployProcess(name="worker", command="python -m extensions.worker", env={"QUEUE": "jobs"}),
    IRDeployProcess(name="beat", command=("python", "-m", "extensions.beat")),
)


def _bundle(tmp_path, **deploy):
    (tmp_path / "extensions").mkdir()
    return deploy_bundle(tmp_path, backend=IRDeployBackend(packages=("extensions",), processes=_PROCESSES), **deploy)


def test_one_service_per_process(tmp_path):
    services = _bundle(tmp_path).services
    assert {"api", "worker", "beat"} <= services.keys()
    assert "app" not in services


def test_processes_share_backend_image_and_env_file(tmp_path):
    services = _bundle(tmp_path).services
    for name in ("api", "worker", "beat"):
        assert services[name]["image"] == "app/backend:${IMAGE_TAG:-latest}"
        assert services[name]["env_file"] == [{"path": ".env", "required": False}]
        assert services[name]["restart"] == "unless-stopped"


def test_only_asgi_process_builds_publishes_and_is_probed(tmp_path):
    services = _bundle(tmp_path).services
    assert services["api"]["build"]["context"] == "./backend"
    assert services["api"]["ports"] == ["${BIND_ADDRESS:-0.0.0.0}:${APP_PORT:-8000}:8000"]
    assert "healthcheck" in services["api"]
    for worker in ("worker", "beat"):
        assert not {"build", "ports", "healthcheck"} & services[worker].keys()


def test_command_processes_keep_their_command_form(tmp_path):
    services = _bundle(tmp_path).services
    assert services["worker"]["command"] == "python -m extensions.worker"
    assert services["beat"]["command"] == ["python", "-m", "extensions.beat"]
    assert "command" not in services["api"]


def test_process_env_extends_app_environment(tmp_path):
    services = _bundle(tmp_path).services
    assert "QUEUE=jobs" in services["worker"]["environment"]
    assert "QUEUE=jobs" not in services["api"]["environment"]
    assert set(services["api"]["environment"]) <= set(services["worker"]["environment"])


def test_registry_names_images(tmp_path):
    services = _bundle(tmp_path, docker=IRDeployDocker(registry="ghcr.io/acme/shop")).services
    assert services["worker"]["image"] == "ghcr.io/acme/shop/backend:${IMAGE_TAG:-latest}"


def test_backend_image_serves_asgi_process(tmp_path):
    dockerfile = _bundle(tmp_path).read("backend/Dockerfile")
    assert dockerfile.rstrip().endswith('CMD ["uvicorn", "extensions.main:app", "--host", "0.0.0.0", "--port", "8000"]')


def test_compose_resolves_processes(tmp_path):
    services = compose_config(_bundle(tmp_path))["services"]
    assert services["worker"]["command"] == ["python", "-m", "extensions.worker"]
    assert services["api"]["healthcheck"]["test"][0] == "CMD"


def test_process_waits_for_setup_and_retains_datastore_dependencies(tmp_path):
    from yaml_api_generator.generators.deploy.generate import generate_deploy
    from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir
    from .support.deploy import DeployBundle
    from .test_deploy_validation import _write

    spec = _write(tmp_path, {
        "backend": {"processes": {"api": {
            "asgi": "app:app", "depends_on": {"setup": "service_completed_successfully"},
        }}},
        "services": {"setup": {"image": "busybox", "command": ["true"]}},
    }, datastores={"primary": {"type": "mongodb", "uri": "mongodb://localhost:27017", "database": "shop"}})
    generate_deploy(load_and_generate_ir(spec).ir, str(tmp_path / "out"), tmp_path)
    api = compose_config(DeployBundle(tmp_path / "out"))["services"]["api"]
    assert api["depends_on"]["setup"]["condition"] == "service_completed_successfully"
    assert api["depends_on"]["mongodb"]["condition"] == "service_started"
