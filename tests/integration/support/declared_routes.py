"""Specs whose controllers declare the register and login routes, exercised identically on every server and target."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_REPOSITORY = Path(__file__).parents[3]

PASSWORD = "correct-horse-battery"


@dataclass(frozen=True)
class Scenario:
    spec: Path
    prefix: str
    profile: dict = field(default_factory=dict)

    def materialize(self, directory: Path, uri: str, database: str) -> Path:
        """Copy the spec beside its imports into ``directory``, bound to the given MongoDB database."""
        shutil.copytree(self.spec.parent, directory, dirs_exist_ok=True)
        document = yaml.safe_load(self.spec.read_text())
        target = directory / "spec.yaml"
        target.write_text(yaml.safe_dump({**document, "mongo": {"uri": uri, "database": database}}, sort_keys=False))
        return target


SCENARIOS = {
    "auth-users-proposed": Scenario(_REPOSITORY / "examples/comparison/auth-users-proposed.yaml", "/api/v1/auth", {"displayName": "Ada"}),
    "auth-users-v0.2": Scenario(_REPOSITORY / "examples/comparison/auth-users/v0.2.yaml", "/api/v1/auth", {"displayName": "Ada"}),
    "register-beside-record": Scenario(_REPOSITORY / "tests/fixtures/declared-routes/spec.yaml", "/api/users"),
}


def exercise(client, prefix: str, profile: dict) -> dict:
    """Register, then sign in, through the declared routes."""
    identity = {"email": "ada@example.com", "password": PASSWORD}
    registered = client.post(f"{prefix}/register", json={**identity, **profile})
    signed_in = client.post(f"{prefix}/login", json=identity)
    return {"register": registered.status_code, "login": signed_in.status_code, "token": "token" in signed_in.json()}


EXPECTED = {"register": 200, "login": 200, "token": True}
