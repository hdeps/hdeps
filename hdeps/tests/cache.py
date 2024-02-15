import tempfile

import unittest
from pathlib import Path

from ..cache import SimpleCache


class SimpleCacheTest(unittest.TestCase):
    def test_basic(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pd = Path(d)

            c = SimpleCache(pd)

            self.assertEqual(None, c.get("foo"))
            c.set("foo", b"value\n")
            self.assertEqual(b"value\n", c.get("foo"))

            self.assertEqual(
                pd
                / "0"
                / "b"
                / "e"
                / "e"
                / "c"
                / "0beec7b5ea3f0fdbc95d0dd47f3c5bc275da8a33",
                c._local_path("foo"),
            )
            self.assertEqual(6, c._local_path("foo").stat().st_size)

    def test_basic_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pd = Path(d)

            c = SimpleCache(pd, suffix="suf")

            self.assertEqual(None, c.get("foo"))
            c.set("foo", b"value\n")
            self.assertEqual(b"value\n", c.get("foo"))

            self.assertEqual(
                pd
                / "suf"
                / "0"
                / "b"
                / "e"
                / "e"
                / "c"
                / "0beec7b5ea3f0fdbc95d0dd47f3c5bc275da8a33",
                c._local_path("foo"),
            )
            self.assertEqual(6, c._local_path("foo").stat().st_size)

    def test_additional_coverage(self) -> None:
        # cover the appdirs call and ensure it is some kind of path we can
        # manipulate.
        SimpleCache()._local_path("foo")
