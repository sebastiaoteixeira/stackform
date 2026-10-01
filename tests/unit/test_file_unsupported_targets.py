"""Backends without file datastores refuse specs that declare file fields."""

import pytest

from tests.conftest import VALID_DIR
from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


@pytest.fixture(params=[(DRFGenerator, "drf"), (RawASGIGenerator, "raw")], ids=["drf", "raw"])
def target(request):
    generator, name = request.param
    return generator(), name


def test_generation_fails_before_emitting(target, tmp_path):
    generator, name = target
    context = build_context(load_and_generate_ir(str(VALID_DIR / "files-filesystem.yaml")).ir)
    output = tmp_path / "out"
    with pytest.raises(ConfigErrors) as raised:
        generator.generate(context, output)
    (error,) = raised.value.errors
    assert error.code == "BACKEND_FEATURE_UNSUPPORTED"
    assert error.message == f"file fields are not supported by target '{name}'"
    assert error.hint == "Generate for the 'fastapi' backend, or remove file fields"
    assert error.path == "entities.documents.fields.avatar"
    assert not output.exists()
