"""The deploy context resolves processes, packages, the frontend source and environments."""

from dataclasses import replace

import pytest

from tests.conftest import VALID_DIR
from yaml_api_generator.generators.deploy.context import DeployTarget
from yaml_api_generator.generators.deploy.context_builder import IMPLICIT_ENVIRONMENT, build_deploy_context
from yaml_api_generator.generators.deploy.docker.generator import DockerDeployGenerator
from yaml_api_generator.ir import (
    IRDeploy,
    IRDeployBackend,
    IRDeployDocker,
    IRDeployEnvironment,
    IRDeployFrontend,
    IRDeployProcess,
)
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

_IR = load_and_generate_ir(str(VALID_DIR / "auth-oidc.yaml")).ir


def _context(spec_dir, target=DeployTarget(), **deploy):
    return build_deploy_context(replace(_IR, deploy=IRDeploy(runtime="docker", **deploy)), spec_dir, target)


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_default_process_serves_generated_app(tmp_path):
    ctx = _context(tmp_path)
    assert [process.name for process in ctx.processes] == ["app"]
    assert ctx.asgi_process.asgi == "app:app"


def test_asgi_process_is_picked_among_workers(tmp_path):
    processes = (
        IRDeployProcess(name="worker", command="python -m ext.worker"),
        IRDeployProcess(name="api", asgi="ext.main:app"),
    )
    ctx = _context(tmp_path, backend=IRDeployBackend(processes=processes))
    assert ctx.asgi_process.name == "api"


def test_process_clashing_with_datastore_service_rejected(tmp_path):
    processes = (IRDeployProcess(name="mongodb", asgi="app:app"),)
    with pytest.raises(ValueError, match="clash with datastore services"):
        _context(tmp_path, backend=IRDeployBackend(processes=processes))


def test_package_requirements_discovered_sorted(tmp_path):
    for requirements in ("ext/workers/requirements.txt", "ext/requirements.txt", "ext/api/requirements.txt"):
        _write(tmp_path / requirements, "httpx\n")
    _write(tmp_path / "ext" / "main.py")

    (package,) = _context(tmp_path, backend=IRDeployBackend(packages=("ext",))).packages

    assert package.name == "ext"
    assert package.bundle_path == "packages/ext"
    assert package.requirements == ("api/requirements.txt", "requirements.txt", "workers/requirements.txt")


def test_frontend_source_enables_frontend(tmp_path):
    _write(tmp_path / "designs" / "package.json", "{}")
    ctx = _context(tmp_path, frontend=IRDeployFrontend(source="designs", env=("VITE_API_BASE_URL",)))

    assert ctx.has_frontend
    assert ctx.frontend.source == (tmp_path / "designs").resolve()
    assert (ctx.frontend.build, ctx.frontend.output) == ("npm run build", "dist")
    assert ctx.frontend.env == ("VITE_API_BASE_URL",)
    assert not ctx.frontend.locked


def test_frontend_lockfile_selects_clean_install(tmp_path):
    _write(tmp_path / "designs" / "package.json", "{}")
    _write(tmp_path / "designs" / "package-lock.json", "{}")
    assert _context(tmp_path, frontend=IRDeployFrontend(source="designs")).frontend.locked


def test_without_frontend_source_or_ui_no_frontend(tmp_path):
    ctx = _context(tmp_path)
    assert ctx.frontend is None
    assert not ctx.has_frontend


def test_without_environments_implicit_one_targets_host(tmp_path):
    target = DeployTarget(host="example.org", user="deploy")
    ctx = _context(tmp_path, target)
    assert ctx.environments == (IMPLICIT_ENVIRONMENT,)
    assert ctx.target == target


def test_environments_name_their_hosts_at_deploy_time(tmp_path):
    environments = (
        IRDeployEnvironment(name="staging", env={"APP_PORT": "8001"}, secrets=("KEYCLOAK_CLIENT_SECRET",)),
        IRDeployEnvironment(name="production"),
    )
    ctx = _context(tmp_path, environments=environments)
    assert ctx.environments == environments
    assert ctx.target is None


def test_generated_secret_in_environment_rejected(tmp_path):
    environments = (IRDeployEnvironment(name="staging", secrets=("JWT_SECRET",)),)
    with pytest.raises(ValueError, match=r"generated secrets \['JWT_SECRET'\]"):
        _context(tmp_path, environments=environments)


def test_docker_delivery_settings_carried(tmp_path):
    docker = IRDeployDocker(registry="ghcr.io/acme/app", delivery="ssh", retain=5)
    ctx = _context(tmp_path, docker=docker)
    assert (ctx.registry, ctx.delivery, ctx.retain) == ("ghcr.io/acme/app", "ssh", 5)


def test_docker_delivery_defaults(tmp_path):
    ctx = _context(tmp_path)
    assert (ctx.registry, ctx.delivery, ctx.retain) == (None, "registry", 3)


def test_packages_and_frontend_source_staged_into_bundle(tmp_path):
    spec_dir = tmp_path / "spec"
    _write(spec_dir / "ext" / "main.py", "app = None\n")
    _write(spec_dir / "designs" / "package.json", "{}")
    out = tmp_path / "out"
    ctx = _context(spec_dir, backend=IRDeployBackend(packages=("ext",)), frontend=IRDeployFrontend(source="designs"))

    DockerDeployGenerator().generate(ctx, out, spec_dir)

    assert (out / "packages" / "ext" / "main.py").is_file()
    assert (out / "frontend" / "package.json").is_file()


def test_package_enclosing_output_rejected(tmp_path):
    out = tmp_path / "ext" / "out"
    out.mkdir(parents=True)
    ctx = _context(tmp_path, backend=IRDeployBackend(packages=("ext",)))
    with pytest.raises(ValueError, match="excludes the output"):
        DockerDeployGenerator().generate(ctx, out, tmp_path)
