"""File datastores and per-collection file handling for the run server."""

from collections.abc import Callable, Mapping
from dataclasses import asdict

from yaml_api_generator.ir import (
    IRDocument,
    IRFileField,
    IRFileStore,
    IRFilesystemStore,
    IRS3Store,
)
from yaml_api_generator.runtime.files import (
    FileField,
    FileLimits,
    FileStore,
    RecordFiles,
)
from yaml_api_generator.runtime.filesystem_store import FilesystemStore


def _filesystem_store(store: IRFilesystemStore) -> FileStore:
    return FilesystemStore(store.path)


def _s3_store(store: IRS3Store) -> FileStore:
    from yaml_api_generator.runtime.s3_store import (
        S3Store,  # defers loading aiobotocore
    )

    return S3Store(
        store.bucket,
        endpoint=store.endpoint,
        region=store.region,
        access_key=store.access_key,
        secret_key=store.secret_key,
        prefix=store.prefix,
        create_bucket=store.local,
    )


_STORE_BUILDERS: dict[type, Callable[..., FileStore]] = {
    IRFilesystemStore: _filesystem_store,
    IRS3Store: _s3_store,
}


def _build_store(store: IRFileStore) -> FileStore:
    return _STORE_BUILDERS[type(store)](store)


def build_file_stores(ir: IRDocument) -> dict[str, FileStore]:
    return {name: _build_store(store) for name, store in ir.file_stores.items()}


def file_field(field: IRFileField) -> FileField:
    values = asdict(field)
    return FileField(**{**values, "limits": FileLimits(**values["limits"])})


def build_record_files(
    ir: IRDocument, stores: Mapping[str, FileStore]
) -> dict[str, RecordFiles]:
    return {
        name: RecordFiles(
            name,
            {field_name: file_field(field) for field_name, field in collection.files.items()},
            stores,
        )
        for name, collection in ir.collections.items()
        if collection.files
    }
