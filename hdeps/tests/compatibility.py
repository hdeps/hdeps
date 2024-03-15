import unittest
from typing import Dict
from unittest.mock import Mock

from packaging.version import Version

from ..compatibility import requires_python_match


class CompatibilityTest(unittest.TestCase):
    def test_requires_python_match(self) -> None:
        # pretend the env marker says 3.7
        python_version = Version("3.7")
        cache: Dict[str, bool] = {}
        fake_project = Mock(
            versions={
                Version("3.6"): Mock(requires_python="zzz"),
                Version("3.7"): Mock(requires_python=">=3.7"),
                Version("3.8"): Mock(requires_python=">=3.8"),
            }
        )
        # This is repeated to test that we read the cached value correctly.
        self.assertFalse(
            requires_python_match(fake_project, cache, python_version, Version("3.8"))
        )
        self.assertEqual(False, cache[">=3.8"])
        self.assertFalse(
            requires_python_match(fake_project, cache, python_version, Version("3.8"))
        )
        self.assertEqual(False, cache[">=3.8"])

        # This too
        self.assertTrue(
            requires_python_match(fake_project, cache, python_version, Version("3.7"))
        )
        self.assertEqual(True, cache[">=3.7"])
        self.assertTrue(
            requires_python_match(fake_project, cache, python_version, Version("3.7"))
        )
        self.assertEqual(True, cache[">=3.7"])

        # This too
        self.assertTrue(
            requires_python_match(fake_project, cache, python_version, Version("3.6"))
        )
        self.assertEqual(True, cache["zzz"])
        self.assertTrue(
            requires_python_match(fake_project, cache, python_version, Version("3.6"))
        )
        self.assertEqual(True, cache["zzz"])
