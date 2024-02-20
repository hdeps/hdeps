import tempfile
import unittest
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

from pypi_simple import DistributionPackage, PyPISimple

from ..cache import SimpleCache
from ..projects import ProjectVersion

from ._fake_session import FakeSession

DIST_ROOT = Path(__file__).parent.joinpath("demo_project/dist")

EXPECTED_REQS = [
    Requirement("a"),
    Requirement('b; python_version == "3.6"'),
    Requirement('c; extra == "foo"'),
    Requirement('d; python_version == "3.6" and extra == "foo"'),
]


class ProjectMetadataTest(unittest.TestCase):
    def test_wheel(self) -> None:
        pv = ProjectVersion(
            Version("0.0.0"),
            (
                DistributionPackage(
                    project="demo_project",
                    version="0.0.0",
                    digests={},
                    requires_python=None,
                    has_sig=False,
                    filename="demo_project-0.0.0-py3-none-any.whl",
                    url="demo_project-0.0.0-py3-none-any.whl",
                    package_type="wheel",
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as d:
            cache = SimpleCache(Path(d))
            md = pv.get_deps(
                ps=None,  # type: ignore
                session=FakeSession(DIST_ROOT),  # type: ignore
                extracted_metadata_cache=cache,
            )
            self.assertEqual(EXPECTED_REQS, md.reqs)
            self.assertEqual(["foo"], md.extras)
            self.assertEqual(1, cache.stats["pass"])
            self.assertEqual(1, cache.stats["sets"])

            # Now load from cache
            md = pv.get_deps(
                ps=None,  # type: ignore
                session=FakeSession(DIST_ROOT),  # type: ignore
                extracted_metadata_cache=cache,
            )
            self.assertEqual(EXPECTED_REQS, md.reqs)
            self.assertEqual(["foo"], md.extras)
            self.assertEqual(1, cache.stats["hits"])  # inc just this
            self.assertEqual(1, cache.stats["pass"])
            self.assertEqual(1, cache.stats["sets"])

    def test_zip_sdist(self) -> None:
        pv = ProjectVersion(
            Version("0.0.0"),
            (
                DistributionPackage(
                    project="demo_project",
                    version="0.0.0",
                    digests={},
                    requires_python=None,
                    has_sig=False,
                    filename="demo_project-0.0.0.zip",
                    url="demo_project-0.0.0.zip",
                    package_type="sdist",
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as d:
            cache = SimpleCache(Path(d))
            md = pv.get_deps(
                ps=None,  # type: ignore
                session=FakeSession(DIST_ROOT),  # type: ignore
                extracted_metadata_cache=cache,
            )
            self.assertEqual(EXPECTED_REQS, md.reqs)
            self.assertEqual(["foo"], md.extras)
            self.assertEqual(1, cache.stats["pass"])
            self.assertEqual(1, cache.stats["sets"])

            # Now load from cache
            md = pv.get_deps(
                ps=None,  # type: ignore
                session=FakeSession(DIST_ROOT),  # type: ignore
                extracted_metadata_cache=cache,
            )
            self.assertEqual(EXPECTED_REQS, md.reqs)
            self.assertEqual(["foo"], md.extras)
            self.assertEqual(1, cache.stats["hits"])  # inc just this
            self.assertEqual(1, cache.stats["pass"])
            self.assertEqual(1, cache.stats["sets"])

    def test_tar_gz_sdist(self) -> None:
        pv = ProjectVersion(
            Version("0.0.0"),
            (
                DistributionPackage(
                    project="demo_project",
                    version="0.0.0",
                    digests={},
                    requires_python=None,
                    has_sig=False,
                    filename="demo_project-0.0.0.tar.gz",
                    url="demo_project-0.0.0.tar.gz",
                    package_type="sdist",
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as d:
            cache = SimpleCache(Path(d))
            md = pv.get_deps(
                ps=PyPISimple(session=FakeSession(DIST_ROOT)),  # type: ignore
                session=None,  # type: ignore
                extracted_metadata_cache=cache,
            )
            self.assertEqual(EXPECTED_REQS, md.reqs)
            self.assertEqual(["foo"], md.extras)
            self.assertEqual(1, cache.stats["pass"])
            self.assertEqual(1, cache.stats["sets"])

            # Now load from cache
            md = pv.get_deps(
                ps=PyPISimple(session=FakeSession(DIST_ROOT)),  # type: ignore
                session=None,  # type: ignore
                extracted_metadata_cache=cache,
            )
            self.assertEqual(EXPECTED_REQS, md.reqs)
            self.assertEqual(["foo"], md.extras)

            self.assertEqual(1, cache.stats["hits"])  # inc just this
            self.assertEqual(1, cache.stats["pass"])
            self.assertEqual(1, cache.stats["sets"])
