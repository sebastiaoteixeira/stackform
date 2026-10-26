"""Targets without login, callback and code-exchange routes refuse providers that sign users in through the app."""

from pathlib import Path

import pytest
import yaml

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir
from yaml_api_generator.server import build_raw_app

VALID = Path(__file__).parents[1] / "fixtures" / "valid"

# fixture, provider, type
PROVIDERS = [
    pytest.param("auth-saml.yaml", "corporate", "SAML", id="saml"),
    pytest.param("auth-oidc-sql.yaml", "keycloak", "OIDC", id="oidc-app"),
]


def _on_mongo(spec: Path, workdir: Path) -> Path:
    """The spec stored in MongoDB, the one datastore the DRF and raw generators support."""
    document = yaml.safe_load(spec.read_text())
    del document["datastores"]
    moved = workdir / spec.name
    moved.write_text(yaml.safe_dump({**document, "mongo": {"uri": "mongodb://localhost:27017", "database": "db"}}))
    return moved


def _generate(target: str):
    generator = {"drf": DRFGenerator, "raw": RawASGIGenerator}[target]()
    return lambda spec, output: generator.generate(
        build_context(load_and_generate_ir(str(_on_mongo(spec, output.parent))).ir), output
    )


TARGETS = [
    pytest.param("drf", _generate("drf"), id="drf"),
    pytest.param("raw", _generate("raw"), id="raw"),
    pytest.param("raw", lambda spec, output: build_raw_app(str(spec)), id="raw-dev-server"),
]


@pytest.mark.parametrize(("fixture", "provider", "kind"), PROVIDERS)
@pytest.mark.parametrize(("target", "build"), TARGETS)
def test_external_login_is_rejected(tmp_path, monkeypatch, fixture, provider, kind, target, build):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    output = tmp_path / "out"

    with pytest.raises(ConfigErrors) as raised:
        build(VALID / fixture, output)

    (error,) = raised.value.errors
    assert (error.code, error.path) == ("BACKEND_FEATURE_UNSUPPORTED", f"providers.{provider}")
    assert error.message == f"{kind} login through provider '{provider}' is not supported by target '{target}'"
    assert not output.exists()
