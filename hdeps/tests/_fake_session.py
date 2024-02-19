import io
from pathlib import Path
from typing import Any

from requests import Response, Session


class FakeSession:
    def __init__(self, fixture_root: Path) -> None:
        self.fixture_root = fixture_root

    def get(self, url: str, headers: Any = None, timeout: float = 0) -> Response:
        # This is intended to "serve" any files from self.fixture_root, but git
        # checkouts on windows with core.autocrlf alter the line endings of
        # files it thinks are text.  We need the checksums of some text files
        # like the mime documents *.metadata to be consistent.
        text = True
        if "/simple/" in url:
            project = url.strip("/").split("/")[-1]
            local_path = self.fixture_root / f"{project}.html"
        elif url.endswith(".metadata"):
            parts = url.split("/")
            local_path = self.fixture_root / parts[-1]
        elif url.endswith((".gz", ".zip")):
            parts = url.split("/")
            local_path = self.fixture_root / parts[-1]
            text = False
        else:
            raise ValueError(f"Unhandled path {url}")

        data = local_path.read_bytes()
        if text:
            data = data.replace(b"\r\n", b"\n")

        resp = Response()
        resp.raw = io.BytesIO(data)
        resp.status_code = 200
        resp.headers["content-type"] = "text/html"
        return resp


def get_fake_session_fixtures() -> Session:
    return FakeSession(Path(__file__).parent / "fixtures")  # type: ignore
