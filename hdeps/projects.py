from __future__ import annotations

import logging
import sys
import tarfile
import tempfile

from collections import defaultdict
from dataclasses import dataclass, field
from email import message_from_string
from functools import partial
from pathlib import Path
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
            # Wheels can be loaded incrementally, but also provide richer, more
            # reliable metadata.
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

            # Sdists made with setuptools contain a requires.txt
            for pkg in self.packages:
                if pkg.package_type == "sdist":
                    if md_bytes := extracted_metadata_cache.get(
                        pkg.url + "#requires.txt"
                    ):
                        md = md_bytes.decode("utf-8")
                        break

                    if pkg.filename.endswith(".zip"):
                        with kev("extract requires.txt remote", url=pkg.url):
                            f = SeekableHttpFile(
                                pkg.url,
                                get_range=partial(get_range_requests, session=session),
                                check_etag=False,
                            )
                            zf = ZipFile(f)  # type: ignore[arg-type,call-overload,unused-ignore]
                            names = filter_requires_txt_names(zf.namelist())
                            if not names:
                                data = b""  # Allow caching when the file doesn't exist
                            else:
                                data = zf.read(names[0])
                    elif pkg.filename.endswith((".gz", ".bz2")):
                        with kev("extract requires.txt dl"):
                            with tempfile.TemporaryDirectory() as d:
                                pf = Path(d, pkg.filename)
                                ps.download_package(pkg, pf, verify=bool(pkg.digests))
                                with tarfile.TarFile.open(pf) as tf:
                                    names = filter_requires_txt_names(tf.getnames())
                                    if not names:
                                        data = b""  # Allow caching when the file doesn't exist
                                    else:
                                        data = tf.extractfile(names[0]).read()  # type: ignore[union-attr]
                    else:
                        continue  # unknown type, don't cache today

                    buf = []
                    # TODO this doesn't note Provides-Extra today
                    for line in convert_sdist_requires(data.decode("utf-8")):
                        buf.append(f"Requires-Dist: {line}\n")
                    md = "".join(buf)
                    extracted_metadata_cache.set(
                        pkg.url + "#requires.txt", md.encode("utf-8")
                    )
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


def convert_sdist_requires(data: str) -> List[str]:
    # This is reverse engineered from looking at a couple examples, but there
    # does not appear to be a formal spec.  Mentioned at
    # https://setuptools.readthedocs.io/en/latest/formats.html#requires-txt
    current_markers = None
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
    return lst


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
