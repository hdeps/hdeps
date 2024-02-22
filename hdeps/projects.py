from __future__ import annotations

import logging
import sys
import tempfile

from collections import defaultdict
from dataclasses import dataclass, field
from email import message_from_string
from functools import partial
from pathlib import Path
from tarfile import TarFile
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple, TypeVar, Union
from zipfile import ZipFile

import metadata_please
from indexurl import get_index_url

from keke import kev
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pypi_simple import DistributionPackage, ProjectPage, PyPISimple

from requests.sessions import Session

from seekablehttpfile import SeekableHttpFile
from seekablehttpfile.core import get_range_requests

from .cache import SimpleCache
from .types import CanonicalName

LOG = logging.getLogger(__name__)

T = TypeVar("T")
D = TypeVar("D")


def first(it: Iterable[T], default: D) -> Union[T, D]:
    """like any(...) but returns the first truthy value"""
    for x in it:
        if x:
            return x
    return default


@dataclass(frozen=True)
class Project:
    name: CanonicalName
    versions: Dict[Version, ProjectVersion]

    @classmethod
    def from_pypi_simple_project_page(cls, project_page: ProjectPage) -> Project:
        vers: Dict[Version, List[DistributionPackage]] = defaultdict(list)
        for dp in project_page.packages:
            if dp.version is None:
                LOG.debug("Ignore unset version in %s", dp.filename)
                continue
            try:
                vers[Version(dp.version)].append(dp)
            except InvalidVersion:
                LOG.debug("Ignore invalid version %s in %s", dp.version, dp.filename)
        return cls(
            name=CanonicalName(canonicalize_name(project_page.project)),
            versions={
                v: ProjectVersion(v, tuple(pkgs)) for v, pkgs in sorted(vers.items())
            },
        )


def filter_requires_txt_names(names: List[str]) -> List[str]:
    # TODO: I can't remember why it's <= 2 rather than a specific count
    return [
        name
        for name in names
        if name.endswith("/requires.txt") and name.count("/") <= 2
    ]


@dataclass(frozen=True)
class ProjectVersion:
    version: Version
    packages: Tuple[DistributionPackage, ...] = field(hash=False)

    @property
    def requires_python(self) -> Optional[str]:
        return first((dp.requires_python for dp in self.packages), None)

    @property
    def yanked(self) -> bool:
        return first((dp.is_yanked for dp in self.packages), False)

    @property
    def has_sdist(self) -> bool:
        return any(dp.package_type == "sdist" for dp in self.packages)

    @property
    def has_wheel(self) -> bool:
        return any(dp.package_type == "wheel" for dp in self.packages)

    def get_deps(
        self, ps: PyPISimple, session: Session, extracted_metadata_cache: SimpleCache
    ) -> BasicMetadata:
        best_pkg: Optional[DistributionPackage] = None
        best_score = 0
        with kev("score", count=len(self.packages)):
            for pkg in self.packages:
                if pkg.has_metadata:
                    score = 100
                elif pkg.package_type == "wheel":
                    score = 90
                elif pkg.package_type == "sdist" and pkg.filename.endswith(".zip"):
                    score = 50
                elif pkg.package_type == "sdist":
                    score = 30
                else:
                    LOG.debug("Cannot load metadata from %r", pkg.filename)
                    continue
                assert pkg
                if score > best_score:
                    best_pkg = pkg
                    best_score = score
                elif score == best_score and pkg.filename < best_pkg.filename:  # type: ignore[union-attr]
                    # Ensure consistent ordering for good cache hits
                    best_pkg = pkg

        if best_pkg is None:
            LOG.warning(
                "Cannot load metadata from version %s, no matching packages in %s",
                self.version,
                [dp.filename for dp in self.packages],
            )
            return BasicMetadata()

        md: str
        # Ensure we don't accidentally use this later on; this was the source of a pesky cache bug
        del pkg
        if best_pkg.has_metadata:
            if md_bytes := extracted_metadata_cache.get(best_pkg.url):
                md = md_bytes.decode("utf-8")
            else:
                with kev("pypi_simple.get_package_metadata"):
                    # pypi-simple does the decode for you today; this wastes a
                    # ton of time trying to guess charset, until
                    # https://github.com/jwodder/pypi-simple/pull/22 is merged.
                    md = ps.get_package_metadata(best_pkg)
                    extracted_metadata_cache.set(best_pkg.url, md.encode("utf-8"))
        elif best_pkg.package_type == "wheel":
            # Wheels can be loaded incrementally, but also provide richer, more
            # reliable metadata.
            if md_bytes := extracted_metadata_cache.get(best_pkg.url):
                md = md_bytes.decode("utf-8")
            else:
                with kev("extract metadata remote", url=best_pkg.url):
                    f = SeekableHttpFile(
                        best_pkg.url,
                        get_range=partial(get_range_requests, session=session),
                        check_etag=False,
                    )
                    zf = ZipFile(f)  # type: ignore[arg-type,call-overload,unused-ignore]

                    # These two lines come from warehouse itself
                    name, version, _ = best_pkg.filename.split("-", 2)
                    md_bytes = metadata_please.from_wheel(zf, name)
                    extracted_metadata_cache.set(best_pkg.url, md_bytes)
                md = md_bytes.decode("utf-8")
        elif best_pkg.package_type == "sdist":
            key = best_pkg.url + "#requires.txt"
            if (md_bytes := extracted_metadata_cache.get(key)) is not None:
                md = md_bytes.decode("utf-8")
            else:
                if best_pkg.filename.endswith(".zip"):
                    with kev("extract sdist metadata remote", url=best_pkg.url):
                        f = SeekableHttpFile(
                            best_pkg.url,
                            get_range=partial(get_range_requests, session=session),
                            check_etag=False,
                        )
                        zf = ZipFile(f)  # type: ignore[arg-type,call-overload,unused-ignore]
                        md_bytes = metadata_please.from_zip_sdist(zf)
                else:
                    with kev("extract tar metadata", url=best_pkg.url):
                        with tempfile.TemporaryDirectory() as d:
                            local_path = Path(d, best_pkg.filename)
                            ps.download_package(
                                best_pkg, path=local_path, verify=bool(best_pkg.digests)
                            )
                            with TarFile.open(local_path) as tf:
                                md_bytes = metadata_please.from_tar_sdist(tf)

                extracted_metadata_cache.set(key, md_bytes)
                md = md_bytes.decode("utf-8")

        else:
            raise NotImplementedError(best_pkg)

        reqs: List[Requirement] = []
        extras: List[str] = []
        if md is not None:
            with kev("transform"):
                msg = message_from_string(md)
                if t := msg.get_all("Requires-Dist"):
                    for dep in t:
                        try:
                            reqs.append(Requirement(dep))
                        except InvalidRequirement:
                            LOG.warning(
                                "Skipping invalid requirement %r",
                                dep,
                            )

                if t := msg.get_all("Provides-Extra"):
                    extras = t
        return BasicMetadata(
            reqs, extras, has_sdist=self.has_sdist, has_wheel=self.has_wheel
        )


def convert_sdist_requires(data: str) -> Tuple[List[str], Set[str]]:
    # This is reverse engineered from looking at a couple examples, but there
    # does not appear to be a formal spec.  Mentioned at
    # https://setuptools.readthedocs.io/en/latest/formats.html#requires-txt
    current_markers = None
    extras: Set[str] = set()
    lst: List[str] = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        elif line[:1] == "[" and line[-1:] == "]":
            current_markers = line[1:-1]
            if ":" in current_markers:
                # absl-py==0.9.0 and requests==2.22.0 are good examples of this
                extra, markers = current_markers.split(":", 1)
                if extra:
                    extras.add(extra)
                    current_markers = f"({markers}) and extra == {extra!r}"
                else:
                    current_markers = markers
            else:
                # this is an extras_require
                current_markers = f"extra == {current_markers!r}"
        else:
            if current_markers:
                lst.append(f"{line}; {current_markers}")
            else:
                lst.append(line)
    return lst, extras


@dataclass
class BasicMetadata:
    reqs: Sequence[Requirement] = ()
    extras: Sequence[str] = ()
    has_sdist: bool = False
    has_wheel: bool = False


if __name__ == "__main__":  # pragma: no cover
    from .session import get_retry_session

    s = get_retry_session()
    x = PyPISimple(get_index_url(), session=s)
    p = Project.from_pypi_simple_project_page(
        x.get_project_page(CanonicalName(sys.argv[1]))
    )
    if len(sys.argv) > 2:
        ver = Version(sys.argv[2])
    else:
        ver = list(p.versions)[-1]
    v = p.versions[ver]
    print(f"{sys.argv[1]}=={ver}", v.get_deps(x, s, SimpleCache()))
