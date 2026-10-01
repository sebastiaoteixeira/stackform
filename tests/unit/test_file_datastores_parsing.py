"""File datastore registry, repository file bindings and limit precedence."""

import pytest
import yaml

from tests.conftest import INVALID_DIR, VALID_DIR
from yaml_api_generator.ir import IRFileLimits, IRFilesystemStore, IRPostgres, IRS3Store
from yaml_api_generator.parsers.transformers.v02.datastore_transformer import (
    parse_file_datastores,
)
from yaml_api_generator.parsers.transformers.v02.file_transformer import (
    LimitLayer,
    parse_size,
)
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir

MIB = 1024 ** 2


def _ir(name: str):
    return load_and_generate_ir(str(VALID_DIR / name)).ir


def _errors(name: str):
    with pytest.raises(ConfigErrors) as raised:
        load_and_generate_ir(str(INVALID_DIR / name))
    return raised.value.errors


class TestParseSize:
    @pytest.mark.parametrize("value, expected", [
        (1, 1),
        ("512", 512),
        ("10B", 10),
        ("1KB", 1024),
        ("1.5kb", 1536),
        ("10 MB", 10 * MIB),
        ("2Gb", 2 * 1024 ** 3),
        ("1.9B", 1),
    ])
    def test_valid_sizes_resolve_to_whole_bytes(self, value, expected):
        assert parse_size(value, "p") == (expected, [])

    @pytest.mark.parametrize("value", [0, "0KB", "0.5B", True, "ten", "-1", "1TB"])
    def test_invalid_sizes_are_rejected(self, value):
        size, (error,) = parse_size(value, "api.files.maxSize")
        assert size is None
        assert (error.code, error.path) == ("FILE_SIZE_INVALID", "api.files.maxSize")


class TestLimitLayer:
    def test_higher_level_overrides_without_intersecting(self):
        field = LimitLayer(types=("image/png",))
        store = LimitLayer(max_size=5, types=("application/pdf",))
        assert field.over(store).limits() == IRFileLimits(max_size=5, types=("image/png",))

    def test_unset_levels_fall_back_to_defaults(self):
        assert LimitLayer().limits() == IRFileLimits()
        assert IRFileLimits().max_size == 10 * MIB

    def test_types_are_lowercased_and_deduplicated(self):
        layer, _ = LimitLayer.parse({"types": ["Image/PNG", "image/png"]}, "p")
        assert layer.types == ("image/png",)


class TestFilesystemSpec:
    @pytest.fixture(scope="class")
    def ir(self):
        return _ir("files-filesystem.yaml")

    def test_file_stores_stay_out_of_record_datastores(self, ir):
        assert list(ir.datastores) == ["main"]
        assert ir.file_stores == {"uploads": IRFilesystemStore(
            path="./uploads",
            limits=IRFileLimits(max_size=5 * MIB, types=("image/png", "image/jpeg")),
        )}

    def test_single_file_store_is_the_default_binding(self, ir):
        assert ir.default_file_store == "uploads"
        assert ir.repositories["documents"].files == "uploads"
        assert ir.collections["documents"].file_store == "uploads"

    def test_api_limits_are_exposed_raw(self, ir):
        assert ir.api.files == IRFileLimits(max_size=20 * MIB, types=("application/pdf",))
        assert ir.api.max_files == 4

    @pytest.mark.parametrize("field, limits", [
        ("avatar", IRFileLimits(max_size=1536, types=("image/png", "image/jpeg"))),
        ("attachments", IRFileLimits(max_size=5 * MIB, types=("image/png", "image/jpeg"))),
        ("scans", IRFileLimits(max_size=5 * MIB, types=("application/pdf",))),
    ])
    def test_limits_resolve_field_then_store_then_api(self, ir, field, limits):
        assert ir.collections["documents"].files[field].limits == limits

    def test_arrays_take_max_items_from_field_then_api(self, ir):
        files = ir.collections["documents"].files
        assert (files["attachments"].multiple, files["attachments"].max_items) == (True, 3)
        assert files["scans"].max_items == 4
        assert (files["avatar"].multiple, files["avatar"].max_items) == (False, None)

    def test_field_flags_and_disposition(self, ir):
        files = ir.collections["documents"].files
        assert files["attachments"].disposition == "inline"
        assert files["avatar"].disposition == "attachment"
        assert (files["contract"].required, files["contract"].readonly) == (True, True)

    def test_only_file_fields_are_collected_and_raw_fields_are_kept(self, ir):
        collection = ir.collections["documents"]
        assert list(collection.files) == ["avatar", "attachments", "scans", "contract"]
        assert collection.fields["avatar"] == {"type": "file", "maxSize": "1.5KB"}
        assert ir.has_files


class TestS3Spec:
    @pytest.fixture(scope="class")
    def ir(self):
        return _ir("files-s3.yaml")

    def test_record_family_resolves_its_own_default(self, ir):
        assert ir.default_datastore == "records"
        assert isinstance(ir.datastores["records"], IRPostgres)

    def test_s3_store_carries_its_connection(self, ir):
        assert ir.file_stores["media"] == IRS3Store(
            bucket="app-media", endpoint="http://minio:9000", region="eu-west-1",
            access_key="minio", secret_key="minio-secret", prefix="media/",
        )

    def test_default_flag_picks_the_file_default(self, ir):
        assert ir.default_file_store == "media"
        assert ir.collections["photos"].file_store == "media"

    def test_explicit_binding_overrides_the_default(self, ir):
        assert ir.repositories["reports"].files == "archive"
        assert ir.collections["reports"].files["pdf"].store == "archive"

    def test_store_without_limits_falls_back_to_built_in_defaults(self, ir):
        assert ir.file_stores["archive"].limits is None
        assert ir.collections["reports"].files["pdf"].limits == IRFileLimits(
            max_size=10 * MIB, types=("application/pdf",)
        )
        assert ir.collections["photos"].files["image"].limits.max_size == 2 * 1024 ** 3

    def test_collection_without_file_fields_has_none(self, ir):
        assert ir.collections["tags"].files == {}


@pytest.mark.parametrize("fixture, code, path", [
    ("files-multiple-defaults.yaml", "FILE_DATASTORE_MULTIPLE_DEFAULTS", "datastores.b.default"),
    ("files-no-default.yaml", "FILE_DATASTORE_NO_DEFAULT", "repositories.documents.files"),
    ("files-datastore-required.yaml", "FILE_DATASTORE_REQUIRED", "repositories.documents.files"),
    ("files-unknown-reference.yaml", "FILE_DATASTORE_UNKNOWN_REFERENCE", "repositories.documents.files"),
    ("files-datastore-not-file.yaml", "DATASTORE_NOT_FILE", "repositories.documents.files"),
    ("files-datastore-not-record.yaml", "DATASTORE_NOT_RECORD", "repositories.documents.datastore"),
    ("files-size-invalid.yaml", "FILE_SIZE_INVALID", "entities.document.fields.avatar.maxSize"),
])
def test_invalid_binding_is_rejected(fixture, code, path):
    assert [(error.code, error.path) for error in _errors(fixture)] == [(code, path)]


@pytest.mark.parametrize("fixture, code, key", [
    ("files-missing-path.yaml", "DATASTORE_FILE_MISSING_PATH", "path"),
    ("files-missing-bucket.yaml", "DATASTORE_FILE_MISSING_BUCKET", "bucket"),
])
def test_missing_store_location_is_rejected(fixture, code, key):
    (schema_error,) = _errors(fixture)
    assert (schema_error.code, schema_error.path) == ("SCHEMA_VALIDATION_ERROR", "datastores.uploads")
    spec = yaml.safe_load((INVALID_DIR / fixture).read_text())
    _, _, (error,) = parse_file_datastores(spec)
    assert (error.code, error.path) == (code, f"datastores.uploads.{key}")
