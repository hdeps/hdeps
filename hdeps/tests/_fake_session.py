import io
from pathlib import Path
from typing import Any

from requests import Response, Session


class FakeSession:
    def __init__(self, fixture_root: Path) -> None:
        self.fixture_root = fixture_root

    def request(self, method: str, *args: Any, **kwargs: Any) -> Response:
        if method.lower() == "get":
            return self.get(*args, **kwargs)
        else:
            raise NotImplementedError(method)

    def get(
        self, url: str, headers: Any = {}, timeout: float = 0, stream: bool = False
    ) -> Response:
        # This is intended to "serve" any files from self.fixture_root, but git
        # checkouts on windows with core.autocrlf alter the line endings of
        # files it thinks are text.  We need the checksums of some text files
        # like the mime documents *.metadata to be consistent.
        if headers is None:
            headers = {}
        text = True
        if url.endswith(".metadata"):
            parts = url.split("/")
            local_path = self.fixture_root / parts[-1]
        elif url.endswith((".gz", ".zip", ".whl")):
            parts = url.split("/")
            local_path = self.fixture_root / parts[-1]
            text = False
        elif "/simple/" in url:
            project = url.strip("/").split("/")[-1]
            local_path = self.fixture_root / f"{project}.html"
        else:
            raise ValueError(f"Unhandled path {url}")

        data = local_path.read_bytes()
        if text:
            data = data.replace(b"\r\n", b"\n")

        length = str(len(data))

        resp = Response()
        resp.url = url
        resp.status_code = 200

        if range := headers.get("Range"):
            assert not text
            resp.status_code = 206
            x = range.rsplit("=", 1)[-1]
            if x[0] == "-":
                # bytes from end
                start = max(0, len(data) + int(x))
                data = data[int(x) :]
            else:
                a, b = x.split("-", 1)
                start = int(a)
                data = data[int(a) : int(b) + 1]
            # TODO make these better numbers
            resp.headers["content-range"] = f"bytes {start}-1/{length}"

        resp.raw = io.BytesIO(data)
        resp.headers["content-type"] = "text/html"
        resp.headers["content-length"] = str(len(data))
        return resp


def get_fake_session_fixtures() -> Session:
    return FakeSession(Path(__file__).parent / "fixtures")  # type: ignore
