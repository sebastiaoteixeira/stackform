"""Deploy bundles generated from a fixture spec with its ``deploy:`` section replaced."""

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from tests.conftest import VALID_DIR
from yaml_api_generator.generators.deploy.generate import generate_deploy
from yaml_api_generator.ir import IRDeploy
from yaml_api_generator.parsers.yaml_parser import load_and_generate_ir


class AnsibleLoader(yaml.SafeLoader):
    """Reads Ansible's ``!unsafe`` values as the plain strings they hold."""


AnsibleLoader.add_constructor("!unsafe", AnsibleLoader.construct_scalar)


@dataclass(frozen=True)
class DeployBundle:
    root: Path

    def read(self, path: str) -> str:
        return (self.root / path).read_text()

    def load(self, path: str) -> Any:
        return yaml.load(self.read(path), AnsibleLoader)

    @cached_property
    def filters(self) -> dict[str, Callable]:
        """The Jinja filters the app role's filter plugins add to Ansible."""
        spec = importlib.util.spec_from_file_location("quoting", self.root / "roles/app/filter_plugins/quoting.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.FilterModule().filters()

    @cached_property
    def compose(self) -> dict:
        return self.load("docker-compose.yml")

    @property
    def services(self) -> dict[str, dict]:
        return self.compose["services"]


def deploy_bundle(
    spec_dir: Path, spec: Path = VALID_DIR / "auth-oidc.yaml", runtime: str = "docker", **deploy
) -> DeployBundle:
    """Generate into ``spec_dir/out`` the bundle of ``spec`` deployed with ``deploy`` on ``runtime``."""
    ir = replace(load_and_generate_ir(str(spec)).ir, deploy=IRDeploy(runtime=runtime, **deploy))
    out = spec_dir / "out"
    generate_deploy(ir, str(out), spec_dir)
    return DeployBundle(out)


def compose_config(bundle: DeployBundle) -> dict:
    """The compose file as Docker Compose resolves it; skips without the compose CLI."""
    if not shutil.which("docker") or subprocess.run(
        ["docker", "compose", "version"], capture_output=True, check=False
    ).returncode:
        pytest.skip("docker compose is not installed")
    (bundle.root / ".env").touch()
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=bundle.root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(result.stdout)


def ansible_syntax_check(bundle: DeployBundle, *extra_vars: str) -> None:
    """Ansible's syntax check of the playbook; skips without ansible-playbook."""
    if not shutil.which("ansible-playbook"):
        pytest.skip("ansible-playbook is not installed")
    result = subprocess.run(
        ["ansible-playbook", "--syntax-check", "playbook.yml", *(f"-e{var}" for var in extra_vars)],
        cwd=bundle.root, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
