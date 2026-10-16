import json
import shutil
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import ClassVar, Generic, TypeVar

import yaml
from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from .context import DeployContext
from .staging import BundleStager

_SHARED_DIR = Path(__file__).parent

_SHARED_FILES = (
    ("inventory.yml.jinja", "inventory.yml"),
    ("env.example.jinja", ".env.example"),
    ("playbook.yml.jinja", "playbook.yml"),
    ("roles/app/defaults/main.yml.jinja", "roles/app/defaults/main.yml"),
)

_MONGO_FILES = (("roles/mongodb/tasks/main.yml.jinja", "roles/mongodb/tasks/main.yml"),)

Context = TypeVar("Context", bound=DeployContext)
Ignore = Callable[[str, list[str]], Iterable[str]]


def ansible_unsafe(value) -> str:
    """``value`` as YAML whose strings are tagged ``!unsafe``, so Ansible never templates spec values."""
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(key)}: {ansible_unsafe(item)}" for key, item in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(map(ansible_unsafe, value)) + "]"
    return f"!unsafe {json.dumps(value)}" if isinstance(value, str) else json.dumps(value)


class DeployGenerator(ABC, Generic[Context]):
    """Renders a runtime's bundle from its ``templates/`` over the shared ones, then copies
    the shared and the runtime's ``ansible/`` trees, which never vary, as they are."""

    runtime_dir: ClassVar[Path]
    roles: ClassVar[tuple[str, ...]] = ("app",)

    def generate(self, ctx: Context, output_dir: Path, spec_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        ctx = self.stage(ctx, BundleStager(spec_dir, output_dir))
        env = self._environment()
        for template, destination in (*_SHARED_FILES, *(_MONGO_FILES if ctx.mongo_local else ()), *self.files(ctx)):
            self._render(env, template, output_dir / destination, ctx=ctx, roles=self.roles)
        for environment in ctx.environments:
            self._render(
                env, "group_vars/environment.yml.jinja", output_dir / "group_vars" / f"{environment.name}.yml",
                ctx=ctx, environment=environment,
            )
        for root in (_SHARED_DIR, self.runtime_dir):
            shutil.copytree(root / "ansible", output_dir, dirs_exist_ok=True, ignore=self.ignore(ctx))

    @abstractmethod
    def stage(self, ctx: Context, stager: BundleStager) -> Context:
        """Copy the hand-written sources into the bundle and return the context the templates render."""

    def files(self, ctx: Context) -> Iterable[tuple[str, str]]:
        """The runtime's own ``(template, bundle path)`` pairs."""
        return ()

    def ignore(self, ctx: Context) -> Ignore | None:
        """The ``shutil.copytree`` filter of the Ansible files this bundle leaves out."""
        return None

    def _environment(self) -> Environment:
        env = Environment(
            loader=ChoiceLoader([FileSystemLoader(self.runtime_dir / "templates"), FileSystemLoader(_SHARED_DIR / "templates")]),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        env.filters["to_yaml"] = lambda v: yaml.dump(v, default_flow_style=False, sort_keys=False).rstrip()
        env.filters["unsafe"] = ansible_unsafe
        return env

    @staticmethod
    def _render(env: Environment, template: str, destination: Path, **variables) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(env.get_template(template).render(**variables))
