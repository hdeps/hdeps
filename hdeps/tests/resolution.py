import io
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from packaging.requirements import Requirement
from pypi_simple import PyPISimple

from ..cache import NoCache
from ..markers import EnvironmentMarkers
from ..resolution import Walker

from ._fake_session import FakeSession


class ResolutionTest(unittest.TestCase):
    # These two tests are just belt-and-suspenders; they do are identical to two of the
    # cli_scenarios tests but without invoking through click, just to ensure the api
    # remains stable.
    def test_simple_integration(self) -> None:
        session = FakeSession(Path(__file__).parent / "fixtures")
        pypi_simple = PyPISimple(session=session)  # type: ignore[arg-type]
        env_markers = EnvironmentMarkers.from_args("3.7.5", None)
        runner = CliRunner()
        with runner.isolated_filesystem():
            walker = Walker(
                1,
                env_markers,
                pypi_simple,
                session,  # type: ignore[arg-type]
                extracted_metadata_cache=NoCache(),
            )
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
        runner = CliRunner()
        with runner.isolated_filesystem():
            walker = Walker(
                1,
                env_markers,
                pypi_simple,
                session,  # type: ignore[arg-type]
                extracted_metadata_cache=NoCache(),
            )
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
