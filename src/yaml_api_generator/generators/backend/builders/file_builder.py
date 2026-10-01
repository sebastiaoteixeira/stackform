"""File datastore and file route building for backend code generation."""

from collections.abc import Callable

from yaml_api_generator.ir import (
    IRDocument,
    IRFileRoute,
    IRFileStore,
    IRFilesystemStore,
    IRS3Store,
)

from ..compile_context import (
    FileRouteDescriptor,
    FileStoreDescriptor,
    FilesystemStoreDescriptor,
    RouteDescriptor,
    S3StoreDescriptor,
)

_STORE_DESCRIPTORS: dict[type, Callable[[str, IRFileStore], FileStoreDescriptor]] = {
    IRFilesystemStore: lambda name, store: FilesystemStoreDescriptor(name=name, path=store.path),
    IRS3Store: lambda name, store: S3StoreDescriptor(
        name=name,
        bucket=store.bucket,
        endpoint=store.endpoint,
        region=store.region,
        access_key=store.access_key,
        secret_key=store.secret_key,
        prefix=store.prefix,
        local=store.local,
    ),
}


class FileBuilder:
    """Builds the file datastore and file route descriptors of a document."""

    def build_file_stores(self, document: IRDocument) -> dict[str, FileStoreDescriptor]:
        used = {f.store for col in document.collections.values() for f in col.files.values()}
        return {
            name: _STORE_DESCRIPTORS[type(store)](name, store)
            for name, store in document.file_stores.items()
            if name in used
        }

    def build_file_routes(
        self, document: IRDocument, routes: list[RouteDescriptor]
    ) -> list[FileRouteDescriptor]:
        sources = {(route.method, route.path): route for route in routes}
        return [
            self._file_route(document, route, sources[(route.source.method, route.source.path)])
            for route in document.file_routes
        ]

    @staticmethod
    def _file_route(
        document: IRDocument, route: IRFileRoute, source: RouteDescriptor
    ) -> FileRouteDescriptor:
        return FileRouteDescriptor(
            action=route.action,
            method=route.method,
            relative_path=source.relative_path + route.path.removeprefix(source.path),
            collection=route.collection,
            field=document.collections[route.collection].files[route.field],
            item=route.item,
            source=source,
            writable=not any(
                rule.write_fields and route.field not in rule.write_fields
                for rule in route.source.access_rules or ()
            ),
        )
