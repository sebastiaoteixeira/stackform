"""The frontend image serves a hand-written or generated app with runtime config and an API proxy."""

from pathlib import Path

import pytest

from yaml_api_generator.ir import IRDeployBackend, IRDeployFrontend, IRDeployProcess

from .support.deploy import compose_config, docker_bundle

EXAMPLES_DIR = Path(__file__).parents[2] / "examples" / "valid"

_FRONTEND = IRDeployFrontend(
    source="designs",
    build="npm run build:prod",
    output="build",
    env=("VITE_AUTH_AUTHORITY", "VITE_API_BASE_URL"),
    args=("VITE_RELEASE",),
    secrets=("NPM_TOKEN",),
)


@pytest.fixture
def designs(tmp_path):
    (tmp_path / "designs").mkdir()
    (tmp_path / "designs" / "package.json").write_text("{}")
    return tmp_path / "designs"


def _bundle(tmp_path, frontend=_FRONTEND, **deploy):
    return docker_bundle(tmp_path, frontend=frontend, **deploy)


def test_source_built_with_its_command_and_output(tmp_path, designs):
    dockerfile = _bundle(tmp_path).read("frontend/Dockerfile")
    assert "npm run build:prod" in dockerfile
    assert "COPY --from=builder /app/build /usr/share/nginx/html" in dockerfile
    assert (tmp_path / "out" / "frontend" / "package.json").is_file()


def test_lockfile_selects_clean_install(tmp_path, designs):
    (designs / "package-lock.json").write_text("{}")
    dockerfile = _bundle(tmp_path).read("frontend/Dockerfile")
    assert "COPY package.json package-lock.json ./" in dockerfile
    assert "npm ci" in dockerfile


def test_without_lockfile_plain_install(tmp_path, designs):
    dockerfile = _bundle(tmp_path).read("frontend/Dockerfile")
    assert "npm install" in dockerfile
    assert "npm ci" not in dockerfile


def test_secrets_mounted_into_install_and_build(tmp_path, designs):
    bundle = _bundle(tmp_path)
    mount = "--mount=type=secret,id=npm_token,env=NPM_TOKEN"
    assert bundle.read("frontend/Dockerfile").count(mount) == 2
    assert bundle.services["frontend"]["build"]["secrets"] == ["npm_token"]
    assert bundle.compose["secrets"] == {"npm_token": {"environment": "NPM_TOKEN"}}


def test_args_are_build_time_only(tmp_path, designs):
    bundle = _bundle(tmp_path)
    assert "ARG VITE_RELEASE" in bundle.read("frontend/Dockerfile")
    assert bundle.services["frontend"]["build"]["args"] == {"VITE_RELEASE": "${VITE_RELEASE:-}"}
    assert not any(line.startswith("VITE_RELEASE=") for line in bundle.services["frontend"]["environment"])


def test_env_names_served_through_runtime_config(tmp_path, designs):
    bundle = _bundle(tmp_path)
    assert bundle.read("nginx/config.js.template") == (
        "window.__CONFIG__ = {\n"
        '  "VITE_AUTH_AUTHORITY": "${VITE_AUTH_AUTHORITY}",\n'
        '  "VITE_API_BASE_URL": "${VITE_API_BASE_URL}",\n'
        "};\n"
    )
    environment = bundle.services["frontend"]["environment"]
    assert {"VITE_AUTH_AUTHORITY=${VITE_AUTH_AUTHORITY:-}", "VITE_API_BASE_URL=${VITE_API_BASE_URL:-}"} <= set(environment)


def test_nginx_templates_copied_from_named_context(tmp_path, designs):
    bundle = _bundle(tmp_path)
    assert "COPY --from=nginx . /etc/nginx/templates/" in bundle.read("frontend/Dockerfile")
    assert bundle.services["frontend"]["build"]["additional_contexts"] == {"nginx": "./nginx"}
    nginx = bundle.read("nginx/default.conf.template")
    assert "proxy_pass ${BACKEND_URL};" in nginx
    assert "alias /etc/nginx/conf.d/config.js;" in nginx


def test_frontend_proxies_to_healthy_asgi_process(tmp_path, designs):
    processes = (IRDeployProcess(name="worker", command="python -m ext.worker"), IRDeployProcess(name="api", asgi="ext.main:app"))
    (tmp_path / "ext").mkdir()
    frontend = _bundle(tmp_path, backend=IRDeployBackend(packages=("ext",), processes=processes)).services["frontend"]
    assert "BACKEND_URL=http://api:8000" in frontend["environment"]
    assert frontend["depends_on"] == {"api": {"condition": "service_healthy"}}
    assert frontend["image"] == "app/frontend:${IMAGE_TAG:-latest}"


def test_generated_frontend_reads_api_url_at_runtime(tmp_path):
    bundle = docker_bundle(tmp_path, spec=EXAMPLES_DIR / "blog-with-ui.yaml")
    dockerfile = bundle.read("frontend/Dockerfile")
    assert "npm run build" in dockerfile
    assert "ARG " not in dockerfile
    assert '"VITE_API_BASE_URL": "${VITE_API_BASE_URL}"' in bundle.read("nginx/config.js.template")
    assert "secrets" not in bundle.compose


def test_without_frontend_no_frontend_artifacts(tmp_path):
    bundle = docker_bundle(tmp_path)
    assert "frontend" not in bundle.services
    assert not (bundle.root / "frontend").exists()
    assert not (bundle.root / "nginx").exists()


def test_compose_accepts_frontend(tmp_path, designs):
    config = compose_config(_bundle(tmp_path))
    assert config["services"]["frontend"]["build"]["secrets"][0]["source"] == "npm_token"
