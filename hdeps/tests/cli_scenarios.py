import logging
import os
import re
import shlex
import unittest
from pathlib import Path
from typing import List, Optional, Tuple
from unittest.mock import patch

from click.testing import CliRunner
from parameterized import parameterized

from ..cache import NoCache
from ..cli import main

from ._fake_session import get_fake_session_fixtures

SCENARIOS: List[Tuple[str, Path]] = sorted(
    # The first item in the tuple is special for parameterized and gets mangled
    # into the test name.  It needs to be a valid identifier, so we still use
    # subTest below to get the actual filename printed for copy-pasting.
    (p.with_suffix("").name, p)
    for p in Path(__file__).parent.joinpath("scenarios").glob("*.txt")
)

LOG_LINE_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} ", re.M)
LOG_LINE_NUMERIC_LINE_RE = re.compile(r"^([A-Z]+\s+[a-z_.]+:)\d+(?= )", re.M)


def load_scenario(path: Path) -> Tuple[Tuple[str, ...], str]:
    command: Optional[Tuple[str, ...]] = None
    output: str = ""
    state = 0
    with open(path) as f:
        for line in f:
            if state == 0 and line.startswith("#"):
                pass
            elif state == 0 and line.startswith("$"):
                parts = shlex.split(line[1:])
                assert parts[0] == "hdeps"
                command = tuple(parts[1:])
                state = 1
            elif state == 1:
                output += line

    assert state == 1
    assert command is not None
    return (command, output)


def save_scenario(path: Path, new_output: str) -> None:
    state = 0
    buf = ""
    with open(path) as f:
        for line in f:
            if state == 0 and line.startswith("#"):
                buf += line
            elif state == 0 and line.startswith("$"):
                buf += line
                state = 1

    assert state == 1
    if not buf.endswith("\n"):
        buf += "\n"
    path.write_text(buf + new_output)


class CliScenariosTest(unittest.TestCase):
    maxDiff = None

    @parameterized.expand(SCENARIOS)  # type:ignore[misc]
    @patch("hdeps.cli.get_retry_session", get_fake_session_fixtures)
    @patch("hdeps.cli.get_cached_retry_session", get_fake_session_fixtures)
    @patch("hdeps.cli.SimpleCache", lambda: NoCache())
    def test_scenario(self, _unused_name: str, path: Path) -> None:
        with self.subTest(path):
            command, output = load_scenario(path)

            runner = CliRunner()
            with runner.isolated_filesystem():
                del logging.root.handlers[:]
                result = runner.invoke(main, command, catch_exceptions=False)

            cleaned_output = LOG_LINE_TIMESTAMP_RE.sub("", result.output)
            cleaned_output = LOG_LINE_NUMERIC_LINE_RE.sub(
                lambda m: (m.group(1) + "<n>"), cleaned_output
            )

            if os.getenv("UPDATE_SCENARIOS"):
                save_scenario(path, cleaned_output)
            else:
                self.assertEqual(output, cleaned_output)
