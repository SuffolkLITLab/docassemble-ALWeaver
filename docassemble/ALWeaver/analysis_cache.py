"""Small process-local caches of JSON results, never live Interview objects."""

from collections import OrderedDict
import hashlib
import json
import os
import stat
import threading
import time
from typing import Any, Callable


def file_stamp(path: str, content: bool = False) -> tuple:
    info = os.stat(path)
    digest = None
    if content and stat.S_ISREG(info.st_mode):
        with open(path, "rb") as stream:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: stream.read(65536), b""):
                hasher.update(chunk)
            digest = hasher.hexdigest()
    return info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, digest


class Dependencies:
    def __init__(self) -> None:
        self.stamps: dict[str, tuple] = {}
        self.content_paths: set[str] = set()
        self.cacheable = True

    def add(self, path: str, content: bool = True) -> None:
        try:
            if content:
                self.content_paths.add(path)
            stamp = file_stamp(path, path in self.content_paths)
            if path in self.stamps and self.stamps[path] != stamp:
                self.cacheable = False
            self.stamps[path] = stamp
            if len(self.stamps) > 512:
                self.cacheable = False
        except (OSError, TypeError):
            self.cacheable = False

    def unchanged(self) -> bool:
        if not self.cacheable or not self.stamps:
            return False
        try:
            return all(
                file_stamp(path, path in self.content_paths) == stamp
                for path, stamp in self.stamps.items()
            )
        except OSError:
            return False

    def source(self, source: Any) -> None:
        """Track even empty/transitive includes, and decline dynamic sources."""
        path = getattr(source, "filepath", None)
        if not isinstance(path, str):
            self.cacheable = False
            return
        self.add(path)
        # Directory changes can introduce a relative include that shadows a
        # package fallback, even though the previously resolved file is intact.
        self.add(os.path.dirname(path), content=False)
        try:
            with open(path, encoding="utf-8") as stream:
                content = stream.read()
            if content.startswith("# use jinja") or content != source.content:
                self.cacheable = False
        except (OSError, UnicodeError):
            self.cacheable = False


class FileResultCache:
    """Bound serialized memory, lifetime, and concurrent same-key computation.

    Each result is decoded afresh, so callers cannot contaminate cached data.
    Fixed lock stripes avoid an unbounded registry of locks. A cache hit checks
    all captured dependencies; a mutation during computation prevents storage.
    """

    def __init__(self, max_bytes: int = 2 * 1024 * 1024, ttl: float = 60) -> None:
        self.max_bytes = max_bytes
        self.ttl = ttl
        self._entries: OrderedDict[Any, tuple[float, Dependencies, bytes]] = (
            OrderedDict()
        )
        self._bytes = 0
        self._guard = threading.Lock()
        self._locks = [threading.Lock() for _ in range(16)]

    def get(self, key: Any, compute: Callable[[Dependencies], Any]) -> Any:
        with self._locks[hash(key) % len(self._locks)]:
            with self._guard:
                entry = self._entries.get(key)
            if (
                entry
                and time.monotonic() - entry[0] < self.ttl
                and entry[1].unchanged()
            ):
                with self._guard:
                    if key in self._entries:
                        self._entries.move_to_end(key)
                return json.loads(entry[2])
            dependencies = Dependencies()
            result = compute(dependencies)
            encoded = json.dumps(result).encode("utf-8")
            cacheable = (
                len(encoded) <= min(self.max_bytes, 256 * 1024)
                and dependencies.unchanged()
            )
            with self._guard:
                previous = self._entries.pop(key, None)
                if previous:
                    self._bytes -= len(previous[2])
                if cacheable:
                    self._entries[key] = (time.monotonic(), dependencies, encoded)
                    self._bytes += len(encoded)
                    while self._bytes > self.max_bytes or len(self._entries) > 32:
                        self._bytes -= len(self._entries.popitem(last=False)[1][2])
            return result
