"""FileStore keeping file bytes under a local directory."""

from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path
from uuid import uuid4

import anyio

from .files import StoredFileNotFoundError

CHUNK_SIZE = 64 * 1024
TEMP_DIR = ".tmp"


class FilesystemStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._temp = self._root / TEMP_DIR

    async def open(self) -> None:
        await anyio.Path(self._temp).mkdir(parents=True, exist_ok=True)

    async def close(self) -> None:
        pass

    async def put(self, key: str, chunks: AsyncIterable[bytes]) -> None:
        target = anyio.Path(self._path(key))
        temp = anyio.Path(self._temp / uuid4().hex)
        try:
            async with await anyio.open_file(temp, "wb") as output:
                async for chunk in chunks:
                    await output.write(chunk)
            await target.parent.mkdir(parents=True, exist_ok=True)
            await temp.replace(target)
        finally:
            with anyio.CancelScope(shield=True):
                await temp.unlink(missing_ok=True)

    def get(self, key: str) -> AsyncIterator[bytes]:
        path = self._path(key)
        if not path.is_file():
            raise StoredFileNotFoundError(f"Stored file '{key}' not found")
        return self._read(path)

    async def delete(self, key: str) -> None:
        await anyio.Path(self._path(key)).unlink(missing_ok=True)

    @staticmethod
    async def _read(path: Path) -> AsyncIterator[bytes]:
        async with await anyio.open_file(path, "rb") as source:
            while chunk := await source.read(CHUNK_SIZE):
                yield chunk

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        unsafe = "\\" in key or parts[0] == TEMP_DIR or any(part in ("", ".", "..") for part in parts)
        if unsafe:
            raise ValueError(f"Invalid storage key '{key}'")
        return self._root.joinpath(*parts)
