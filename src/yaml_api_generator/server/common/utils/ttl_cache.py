"""Bounded mapping whose entries expire after a fixed time-to-live."""

import time
from collections import OrderedDict
from collections.abc import Callable, Iterator, MutableMapping
from typing import TypeVar

DEFAULT_TTL_SECONDS = 300.0
DEFAULT_MAX_ENTRIES = 128

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(MutableMapping[K, V]):
    def __init__(
        self,
        ttl: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def _drop_expired(self) -> None:
        now = self._clock()
        for key in [k for k, (expires_at, _) in self._entries.items() if expires_at <= now]:
            del self._entries[key]

    def __getitem__(self, key: K) -> V:
        self._drop_expired()
        _, value = self._entries[key]
        self._entries.move_to_end(key)
        return value

    def __setitem__(self, key: K, value: V) -> None:
        self._drop_expired()
        self._entries[key] = (self._clock() + self._ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def __delitem__(self, key: K) -> None:
        del self._entries[key]

    def __iter__(self) -> Iterator[K]:
        self._drop_expired()
        return iter(self._entries)

    def __len__(self) -> int:
        self._drop_expired()
        return len(self._entries)
