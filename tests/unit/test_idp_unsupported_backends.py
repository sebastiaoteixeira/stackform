"""Backends without IdP token verification must refuse to generate trust: idp.

Emitting a backend that quietly skips the verification a spec asked for is a
security hole dressed as a successful build, so generation fails instead.
"""

import textwrap

import pytest

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

_SPEC = """
version: "0.2"
api:
  basePath: /api
  version: v1
providers:
  keycloak:
    type: oidc
    trust: {trust}
    client_id: my-app
    discovery_url: "http://keycloak.test/.well-known/openid-configuration"
    audiences: ["my-app"]
mongo:
  uri: mongodb://localhost:27017
  database: testdb
entities:
  user:
    type: auth
    auth:
      identifier: email
      via:
        - provider: keycloak
          identifier: email
          claim_mapping:
            email: email
          auto_provision: true
    fields:
      id: {{ type: id }}
      email: {{ type: string, required: true, unique: true }}
      name: {{ type: string }}
repositories:
  users:
    entity: user
services:
  users:
    repository: users
controllers:
  users:
    service: users
    base_path: /users
    access: "*"
"""


def _context(tmp_path, trust: str):
    spec = tmp_path / f"{trust}-trust.yaml"
    spec.write_text(textwrap.dedent(_SPEC.format(trust=trust)))
    return build_context(load_and_generate_ir(str(spec)).ir)


@pytest.fixture(params=[DRFGenerator, RawASGIGenerator], ids=["drf", "raw"])
def generator(request):
    return request.param()


class TestIdpTrustRejected:
    def test_generation_fails(self, generator, tmp_path):
        with pytest.raises(ConfigErrors):
            generator.generate(_context(tmp_path, "idp"), tmp_path / "out")

    def test_error_names_the_provider_feature_and_backend(self, generator, tmp_path):
        with pytest.raises(ConfigErrors) as raised:
            generator.generate(_context(tmp_path, "idp"), tmp_path / "out")
        (error,) = raised.value.errors
        assert "keycloak" in error.message
        assert "trust: idp" in error.message
        assert error.path == "providers.keycloak.trust"
        assert error.hint

    def test_nothing_is_emitted(self, generator, tmp_path):
        output = tmp_path / "out"
        with pytest.raises(ConfigErrors):
            generator.generate(_context(tmp_path, "idp"), output)
        assert not output.exists()
