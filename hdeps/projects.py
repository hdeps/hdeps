from __future__ import annotations

import logging

import sys

from collections import defaultdict
from dataclasses import dataclass, field
from email import message_from_string
from functools import partial
from typing import Dict, List, Optional, Sequence, Tuple
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
            versions={
                v: ProjectVersion(v, tuple(pkgs), None, False)
                for v, pkgs in vers.items()
            },
        )


@dataclass(frozen=True)
class ProjectVersion:
    version: LooseVersion
    packages: Tuple[DistributionPackage, ...] = field(hash=False)
    requires_python: Optional[str]
    yanked: bool

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
                        zf = ZipFile(f)  # type: ignore[arg-type]
                        # These two lines come from warehouse itself
                        name, version, _ = pkg.filename.split("-", 2)
                        md_bytes = zf.read(f"{name}-{version}.dist-info/METADATA")
                        extracted_metadata_cache.set(pkg.url, md_bytes)
                    md = md_bytes.decode("utf-8")
                    break

        assert md is not None
        with kev("transform"):
            msg = message_from_string(md)
            reqs: List[Requirement] = []
            deps = msg.get_all("Requires-Dist")
            if deps:
                for dep in deps:
                    try:
                        reqs.append(Requirement(dep))
                    except InvalidRequirement:
                        LOG.warning(
                            "Skipping invalid requirement %r",
                            dep,
                        )

            extras: Optional[List[str]] = msg.get_all("Provides-Extra")
            if extras is None:
                extras = []
        return BasicMetadata(reqs, extras)


@dataclass
class BasicMetadata:
    reqs: Sequence[Requirement] = ()
    extras: Sequence[str] = ()


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
