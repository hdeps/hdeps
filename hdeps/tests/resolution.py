import io
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from packaging.requirements import Requirement
from pypi_simple import PyPISimple
from requests import Response, Session

from ..cache import SimpleCache

from ..cli import main
from ..markers import EnvironmentMarkers
from ..resolution import Walker


class FakeSession:
    def __init__(self, fixture_root: Path) -> None:
        self.fixture_root = fixture_root

    def get(self, url: str, headers: Any = None, timeout: float = 0) -> Response:
        if "/simple/" in url:
            project = url.strip("/").split("/")[-1]
            local_path = self.fixture_root / f"{project}.html"
        elif url.endswith(".metadata"):
            parts = url.split("/")
            local_path = self.fixture_root / parts[-1]
        else:
            raise ValueError(f"Unhandled path {url}")

        resp = Response()
        resp.raw = io.BytesIO(local_path.read_bytes())
        resp.status_code = 200
        resp.headers["content-type"] = "text/html"
        return resp


def get_fake_session_fixtures() -> Session:
    return FakeSession(Path(__file__).parent / "fixtures")  # type: ignore


class ResolutionTest(unittest.TestCase):
    @patch("hdeps.cli.get_retry_session", get_fake_session_fixtures)
    @patch("hdeps.cli.get_cached_retry_session", get_fake_session_fixtures)
    def test_simple_resolve(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["batman==1"], catch_exceptions=False)
        self.assertEqual(
            """\
batman (==1.0) via ==1
. robin (==1.0) via ==1.0
""",
            result.output,
        )

    @patch("hdeps.cli.get_retry_session", get_fake_session_fixtures)
    @patch("hdeps.cli.get_cached_retry_session", get_fake_session_fixtures)
    def test_simple_resolve_install_order(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main, ["--install-order", "batman==1"], catch_exceptions=False
        )
        self.assertEqual(
            """\
robin==1.0
batman==1.0
""",
            result.output,
        )

    @patch("hdeps.cli.get_retry_session", get_fake_session_fixtures)
    @patch("hdeps.cli.get_cached_retry_session", get_fake_session_fixtures)
    def test_reuse_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["batman==1", "batman"], catch_exceptions=False)
        self.assertEqual(
            """\
batman (==1.0) via ==1
. robin (==1.0) via ==1.0
batman (==1.0) (already listed) via *
""",
            result.output,
        )

    @patch("hdeps.cli.get_retry_session", get_fake_session_fixtures)
    @patch("hdeps.cli.get_cached_retry_session", get_fake_session_fixtures)
    def test_not_a_solver_reuse_version(self) -> None:
        runner = CliRunner(mix_stderr=False)
        with runner.isolated_filesystem():
            with patch("hdeps.resolution.SimpleCache", lambda: SimpleCache(Path("x"))):
                result = runner.invoke(
                    main, ["batman", "batman==1"], catch_exceptions=False
                )
        self.assertEqual(
            """\
batman (==2.0) via *
. robin (==2.0) via >1.0
batman (==1.0) via ==1
. robin (==1.0) via ==1.0
""",
            result.output,
        )
        # TODO ensure we got the correct log messages,
        # 2024-02-15 08:03:31,216 WARNING  hdeps.resolution:143 Multiple versions for batman: 2.0 and 1.0
        # 2024-02-15 08:03:31,217 WARNING  hdeps.resolution:143 Multiple versions for robin: 2.0 and 1.0

    @patch("hdeps.cli.get_retry_session", get_fake_session_fixtures)
    @patch("hdeps.cli.get_cached_retry_session", get_fake_session_fixtures)
    def test_not_a_solver_reuse_non_public_version(self) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            with patch("hdeps.resolution.SimpleCache", lambda: SimpleCache(Path("x"))):
                result = runner.invoke(
                    main, ["--have", "robin==1.5", "batman"], catch_exceptions=False
                )
        self.assertEqual(
            """\
batman (==2.0) via *
. robin (==1.5) via >1.0
""",
            result.output,
        )

    @patch("hdeps.cli.get_retry_session", get_fake_session_fixtures)
    @patch("hdeps.cli.get_cached_retry_session", get_fake_session_fixtures)
    def test_not_a_solver_reuse_non_public_version_without_deps(self) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            with patch("hdeps.resolution.SimpleCache", lambda: SimpleCache(Path("x"))):
                result = runner.invoke(
                    main, ["--have", "batman==1.5", "batman"], catch_exceptions=False
                )
        self.assertEqual(
            """\
batman (==1.5) via *
""",
            result.output,
        )

    def test_simple_integration(self) -> None:
        session = FakeSession(Path(__file__).parent / "fixtures")
        pypi_simple = PyPISimple(session=session)  # type: ignore[arg-type]
        env_markers = EnvironmentMarkers.from_args("3.7.5", None)
        walker = Walker(1, env_markers, pypi_simple, session)  # type: ignore[arg-type]
        walker.feed(Requirement("batman==1"))
        walker.drain()

        new_stdout = io.StringIO()
        with patch("sys.stdout", new_stdout):
            walker.print_flat()

        self.assertEqual(
            """\
robin==1.0
batman==1.0
""",
            new_stdout.getvalue(),
        )

        new_stdout = io.StringIO()
        with patch("sys.stdout", new_stdout):
            walker.print_tree()

        self.assertEqual(
            """\
batman (==1.0) via ==1
. robin (==1.0) via ==1.0
""",
            new_stdout.getvalue(),
        )

    def test_reuse_integration(self) -> None:
        session = FakeSession(Path(__file__).parent / "fixtures")
        pypi_simple = PyPISimple(session=session)  # type: ignore[arg-type]
        env_markers = EnvironmentMarkers.from_args("3.7.5", None)
        walker = Walker(1, env_markers, pypi_simple, session)  # type: ignore[arg-type]
        walker.feed(Requirement("batman==1"))
        walker.drain()

        new_stdout = io.StringIO()
        with patch("sys.stdout", new_stdout):
            walker.print_flat()

        self.assertEqual(
            """\
robin==1.0
batman==1.0
""",
            new_stdout.getvalue(),
        )

        new_stdout = io.StringIO()
        with patch("sys.stdout", new_stdout):
            walker.print_tree()

        self.assertEqual(
            """\
batman (==1.0) via ==1
. robin (==1.0) via ==1.0
""",
            new_stdout.getvalue(),
        )
