"""Resource limits survive parsing and Compose resolution, without changing defaults."""

import pytest

from yaml_api_generator.generators.deploy.generate import generate_deploy
from yaml_api_generator.ir import IRDeployDocker
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir

from .support.deploy import DeployBundle, compose_config, deploy_bundle
from .test_deploy_validation import _codes, _write


def test_resource_budget_reaches_compose(tmp_path):
    spec = _write(tmp_path, {
        "backend": {"processes": {"api": {"asgi": "app:app"}, "worker": {"command": "python -m worker"}}},
        "docker": {"memory_limits": {"api": "192m", "worker": "96m", "mongodb": "512m"}, "mongo_cache_gb": 0.256},
    }, datastores={"primary": {"type": "mongodb", "uri": "mongodb://localhost:27017", "database": "shop"}})
    ir = load_and_generate_ir(spec).ir
    generate_deploy(ir, str(tmp_path / "out"), tmp_path)
    services = compose_config(DeployBundle(tmp_path / "out"))["services"]
    for name, mb in {"api": 192, "worker": 96, "mongodb": 512}.items():
        assert int(services[name]["mem_limit"]) == mb * 1024 * 1024
        assert int(services[name]["memswap_limit"]) == mb * 1024 * 1024
    assert services["mongodb"]["command"] == ["mongod", "--wiredTigerCacheSizeGB", "0.256"]


@pytest.mark.parametrize("value", ["0m", "-1g", "unlimited", "128m\nimage: evil", 128])
def test_invalid_memory_limit_rejected(tmp_path, value):
    assert _codes(tmp_path, {"docker": {"memory_limits": {"app": value}}})[0][0] == "SCHEMA_VALIDATION_ERROR"


@pytest.mark.parametrize("value", [0, 0.25, 10001, "0.256"])
def test_invalid_cache_size_rejected(tmp_path, value):
    assert _codes(tmp_path, {"docker": {"mongo_cache_gb": value}})[0][0] == "SCHEMA_VALIDATION_ERROR"


def test_unknown_service_does_not_silently_lose_limit(tmp_path):
    with pytest.raises(ValueError, match="unknown generated services"):
        deploy_bundle(tmp_path, docker=IRDeployDocker(memory_limits={"typo": "128m"}))


@pytest.mark.parametrize("option", [{"memory_limits": {"app": "128m"}}, {"mongo_cache_gb": 0.256}])
def test_resource_options_require_docker(tmp_path, option):
    assert _codes(tmp_path, {"runtime": "systemd", "docker": option})[0][0] == "DEPLOY_DOCKER_ONLY"


def test_default_bundle_leaves_resource_policy_to_operator(tmp_path):
    for service in deploy_bundle(tmp_path).services.values():
        assert "mem_limit" not in service
        assert "memswap_limit" not in service
