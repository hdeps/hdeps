from __future__ import annotations

import logging

import sys

from collections import defaultdict
from dataclasses import dataclass, field
from email import message_from_string
from functools import partial
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, TypeVar, Union
from zipfile import ZipFile

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
from .types import CanonicalName, LooseVersion

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
    versions: Dict[LooseVersion, ProjectVersion]

    @classmethod
    def from_pypi_simple_project_page(cls, project_page: ProjectPage) -> Project:
        vers: Dict[LooseVersion, List[DistributionPackage]] = defaultdict(list)
        # TODO sort vers
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
            versions={v: ProjectVersion(v, tuple(pkgs)) for v, pkgs in vers.items()},
        )


@dataclass(frozen=True)
class ProjectVersion:
    version: LooseVersion
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
        md: Optional[str] = None
        for pkg in self.packages:
            if pkg.has_metadata:
                if md_bytes := extracted_metadata_cache.get(pkg.url):
                    md = md_bytes.decode("utf-8")
                else:
                    with kev("pypi_simple.get_package_metadata"):
                        md = ps.get_package_metadata(pkg)
                        extracted_metadata_cache.set(pkg.url, md.encode("utf-8"))
                break
        else:
            for pkg in self.packages:
                if pkg.package_type == "wheel":
                    if md_bytes := extracted_metadata_cache.get(pkg.url):
                        md = md_bytes.decode("utf-8")
                        break

                    with kev("extract metadata remote", url=pkg.url):
                        f = SeekableHttpFile(
                            pkg.url,
                            get_range=partial(get_range_requests, session=session),
                            check_etag=False,
                        )
                        zf = ZipFile(f)  # type: ignore[arg-type,call-overload,unused-ignore]
                        # These two lines come from warehouse itself
                        name, version, _ = pkg.filename.split("-", 2)
                        md_bytes = zf.read(f"{name}-{version}.dist-info/METADATA")
                        assert md_bytes is not None
                        extracted_metadata_cache.set(pkg.url, md_bytes)
                    md = md_bytes.decode("utf-8")
                    break

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
