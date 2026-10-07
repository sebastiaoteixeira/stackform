"""Hand-written packages extend the generated backend image in a stage of their own."""

from yaml_api_generator.ir import IRDeployBackend, IRDeployProcess

from .support.deploy import compose_config, docker_bundle

_API = (IRDeployProcess(name="api", asgi="ext.main:app"),)


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _bundle(tmp_path, **backend):
    _write(tmp_path / "ext" / "main.py", "app = None\n")
    return docker_bundle(tmp_path, backend=IRDeployBackend(packages=("ext",), processes=_API, **backend))


def test_without_packages_only_generated_stage(tmp_path):
    dockerfile = docker_bundle(tmp_path).read("backend/Dockerfile")
    assert dockerfile.count("FROM ") == 1
    assert "FROM python:3.11-slim AS generated" in dockerfile


def test_backend_runs_as_unprivileged_user(tmp_path):
    dockerfile = _bundle(tmp_path).read("backend/Dockerfile")
    assert "useradd --uid 10001" in dockerfile
    assert dockerfile.split("FROM generated")[1].count("USER 10001") == 1


def test_package_copied_from_named_context(tmp_path):
    bundle = _bundle(tmp_path)
    assert "FROM generated" in bundle.read("backend/Dockerfile")
    assert "COPY --from=ext . ext/" in bundle.read("backend/Dockerfile")
    assert bundle.services["api"]["build"]["additional_contexts"] == {"ext": "./packages/ext"}
    assert (bundle.root / "packages" / "ext" / "main.py").is_file()


def test_each_requirements_file_installed_in_order(tmp_path):
    for requirements in ("ext/workers/requirements.txt", "ext/requirements.txt"):
        _write(tmp_path / requirements, "httpx\n")
    dockerfile = _bundle(tmp_path).read("backend/Dockerfile")
    root = dockerfile.index("source=requirements.txt,")
    workers = dockerfile.index("source=workers/requirements.txt,")
    assert root < workers < dockerfile.index("COPY --from=ext")


def test_system_packages_installed_as_root(tmp_path):
    dockerfile = _bundle(tmp_path, system_packages=("libpq5", "curl")).read("backend/Dockerfile")
    extension = dockerfile.split("FROM generated")[1]
    assert extension.index("USER root") < extension.index("apt-get install -y --no-install-recommends libpq5 curl")


def test_without_system_packages_no_apt(tmp_path):
    assert "apt-get" not in _bundle(tmp_path).read("backend/Dockerfile")


def test_compose_accepts_package_contexts(tmp_path):
    build = compose_config(_bundle(tmp_path))["services"]["api"]["build"]
    assert build["additional_contexts"]["ext"].endswith("packages/ext")
