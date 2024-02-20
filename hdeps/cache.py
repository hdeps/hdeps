import os
from hashlib import sha1
from pathlib import Path
from tempfile import mkstemp
from typing import Optional

import appdirs


class SimpleCache:
    """
    An extremely simple cache for storing immutable objects.
    """

    def __init__(
        self, cache_path: Optional[Path] = None, suffix: Optional[str] = None
    ) -> None:
        if not cache_path:
            cache_path = Path(appdirs.user_cache_dir("hdeps", "python-packaging"))
        if suffix:
            cache_path = cache_path / suffix

        self.cache_path = cache_path
        self.hash_factory = sha1
        self.stats = {"hits": 0, "pass": 0, "sets": 0}

    def _local_path(self, key: str) -> Path:
        h = self.hash_factory(key.encode("utf-8")).hexdigest()
        return self.cache_path.joinpath(*h[:5], h)

    def get(self, key: str) -> Optional[bytes]:
        p = self._local_path(key)
        try:
            data = p.read_bytes()
            self.stats["hits"] += 1
            return data
        except OSError:
            self.stats["pass"] += 1
            return None

    def set(self, key: str, value: bytes) -> None:
        p = self._local_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        (fd, temp_name) = mkstemp(f".{os.getpid()}", prefix=p.name, dir=p.parent)
        with os.fdopen(fd, "wb") as f:
            f.write(value)

        os.replace(temp_name, p)
        self.stats["sets"] += 1


class NoCache(SimpleCache):
    def get(self, key: str) -> Optional[bytes]:
        return None

    def set(self, key: str, value: bytes) -> None:
        pass
