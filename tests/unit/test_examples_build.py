"""Every shipped example spec builds on the dev server and generates a FastAPI backend."""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from yaml_api_generator.cli.compiler import compile_project
from yaml_api_generator.server import build_app

EXAMPLES = Path(__file__).parents[2] / "examples"
SPECS = sorted(
    path for path in EXAMPLES.rglob("*.yaml") if not {"invalid", "packs"} & set(path.relative_to(EXAMPLES).parts)
)

_EXAMPLES = pytest.mark.parametrize("spec", SPECS, ids=lambda path: str(path.relative_to(EXAMPLES)))


@pytest.fixture(autouse=True)
def dpop_key(monkeypatch):
    """The oidc-pkce-dpop example's provider needs a persistent DPoP signing key."""
    key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    monkeypatch.setenv("IDENTITY_DPOP_PRIVATE_KEY", key.decode())


@_EXAMPLES
def test_example_builds_on_dev_server(spec):
    build_app(str(spec))


@_EXAMPLES
def test_example_generates_fastapi(tmp_path, spec):
    compile_project(yaml_file=spec, output_dir=tmp_path, target="fastapi")
    for source in tmp_path.rglob("*.py"):
        compile(source.read_text(), str(source), "exec")
