"""`yaml-api run --raw` refuses specs with file fields."""

import pytest

from yaml_api_generator.parsers.errors import ConfigErrors
from yaml_api_generator.server import build_raw_app

from .test_run_files import _SPEC


def test_raw_run_rejects_file_fields(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(_SPEC.format(uploads=tmp_path / "uploads"))

    with pytest.raises(ConfigErrors) as excinfo:
        build_raw_app(str(spec))

    [error] = excinfo.value.errors
    assert error.code == "BACKEND_FEATURE_UNSUPPORTED"
    assert error.message == "file fields are not supported by target 'raw'"
    assert error.path == "entities.post.fields.cover"
