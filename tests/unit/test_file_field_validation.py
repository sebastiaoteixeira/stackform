"""Placement, constraint and comparability rules for ``type: file`` fields."""

import pytest

from tests.conftest import INVALID_DIR
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


def _errors(name: str):
    with pytest.raises(ConfigErrors) as raised:
        load_and_generate_ir(str(INVALID_DIR / name))
    return [(error.code, error.path) for error in raised.value.errors]


@pytest.mark.parametrize("fixture, expected", [
    ("files-limit-on-non-file.yaml", ("FIELD_CONSTRAINT_INVALID", "entities.document.fields.title")),
    ("files-max-items-on-non-file-array.yaml", ("FIELD_CONSTRAINT_INVALID", "entities.document.fields.tags")),
    ("files-unique-file.yaml", ("FIELD_CONSTRAINT_INVALID", "entities.document.fields.avatar")),
    ("files-nested.yaml", ("FILE_FIELD_NESTED", "entities.document.fields.profile.properties.avatar")),
    ("files-in-dto.yaml", ("FILE_FIELD_CONTEXT_INVALID", "dto.upload.fields.blob")),
    ("files-in-service-input.yaml", ("FILE_FIELD_CONTEXT_INVALID", "services.notify.input.blob")),
    ("files-sort-key.yaml", (
        "FILE_FIELD_NOT_COMPARABLE", "controllers.documents.operations.list.pagination.sort[0].field",
    )),
    ("files-when-comparison.yaml", (
        "FILE_FIELD_NOT_COMPARABLE", "GET /api/documents/{documentId} access[0].when",
    )),
    ("files-where-comparison.yaml", (
        "FILE_FIELD_NOT_COMPARABLE", "GET /api/documents/{documentId} access[0].given.doc",
    )),
])
def test_misplaced_or_misused_file_field_is_rejected(fixture, expected):
    assert _errors(fixture) == [expected]
