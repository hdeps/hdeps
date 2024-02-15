import unittest

from packaging.requirements import Requirement

from ..markers import EnvironmentMarkers


class EnvironmentMarkersTest(unittest.TestCase):
    def test_platforms(self) -> None:
        e = EnvironmentMarkers(sys_platform="win32")
        self.assertEqual("nt", e.os_name)
        e = EnvironmentMarkers(sys_platform="darwin")
        self.assertEqual("posix", e.os_name)
        e = EnvironmentMarkers(python_version="2.7.5")
        self.assertEqual("linux2", e.sys_platform)
        with self.assertRaises(TypeError):
            e = EnvironmentMarkers(sys_platform="x")

    def test_match(self) -> None:
        req = Requirement("foo ; python_version == '3.6'")

        e = EnvironmentMarkers(python_version="3.6")
        self.assertTrue(e.match(req.marker))

        e = EnvironmentMarkers(python_version="3.7")
        self.assertFalse(e.match(req.marker))

    def test_extras_match(self) -> None:
        req = Requirement("foo ; python_version == '3.6' and extra == 'x'")

        e = EnvironmentMarkers(python_version="3.6")
        self.assertFalse(e.match(req.marker))
        self.assertFalse(e.match(req.marker, []))
        self.assertTrue(e.match(req.marker, ["x"]))
        self.assertTrue(e.match(req.marker, ["x", "y"]))

        e = EnvironmentMarkers(python_version="3.7")
        self.assertFalse(e.match(req.marker))
        self.assertFalse(e.match(req.marker, []))
        self.assertFalse(e.match(req.marker, ["x"]))
        self.assertFalse(e.match(req.marker, ["x", "y"]))
