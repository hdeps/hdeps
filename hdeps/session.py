from typing import Optional

import appdirs
from cachecontrol import CacheControlAdapter
from cachecontrol.caches import SeparateBodyFileCache
from requests.adapters import HTTPAdapter, Retry
from requests.sessions import Session


def get_cached_retry_session(cache_dir: Optional[str] = None) -> Session:
    if not cache_dir:
        cache_dir = appdirs.user_cache_dir("hdeps", "python-packaging")

    sess = Session()
    # Settings copied from pip/_internal/network/session.py
    retries = Retry(
        total=3, backoff_factor=0.25, status_forcelist=[500, 502, 503, 520, 527]
    )
    assert cache_dir is not None
    cache_adapter = CacheControlAdapter(
        cache=SeparateBodyFileCache(cache_dir), max_retries=retries, pool_maxsize=100
    )
    sess.mount("https://", cache_adapter)
    sess.mount("http://", cache_adapter)
    return sess


def get_retry_session() -> Session:
    sess = Session()
    # Settings copied from pip/_internal/network/session.py
    retries = Retry(
        total=3, backoff_factor=0.25, status_forcelist=[500, 502, 503, 520, 527]
    )
    adapter = HTTPAdapter(max_retries=retries, pool_maxsize=100)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


if __name__ == "__main__":
    with get_cached_retry_session() as s:
        s.get(
            "https://pypi.org/simple/example-foo/",
            headers={"cache-control": "max-age=0"},
            # , "range": "bytes=1-10"},
        )
