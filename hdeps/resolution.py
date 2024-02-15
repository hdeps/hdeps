import logging
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor

from pathlib import Path
from typing import Dict, Optional, Set, Tuple

import click

from keke import kev, ktrace

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from pypi_simple import PyPISimple
from requests.sessions import Session

# from tpe_prio import ThreadPoolExecutor

from .cache import SimpleCache

from .compatibility import find_best_compatible_version
from .markers import EnvironmentMarkers
from .projects import BasicMetadata, Project, ProjectVersion
from .requirements import _iter_simple_requirements
from .session import get_retry_session
from .types import CanonicalName, Choice, Edge, LooseVersion, VersionCallback

LOG = logging.getLogger(__name__)


def _all_current_versions_unknown(cn: CanonicalName) -> Optional[str]:
    """
    Default for when you don't need to reuse any already-installed project
    versions.
    """
    return None


class Walker:
    def __init__(
        self,
        parallelism: int,
        env_markers: EnvironmentMarkers,
        pypi_simple: PyPISimple,
        uncached_session: Optional[Session] = None,
        current_version_callback: VersionCallback = _all_current_versions_unknown,
    ):
        self.root = Choice(CanonicalName("-"), Version("0"))
        self.pool = ThreadPoolExecutor(max_workers=parallelism)
        self.env_markers = env_markers
        self.pypi_simple = pypi_simple
        self.uncached_session = uncached_session or get_retry_session()
        self.extracted_metadata_cache = SimpleCache()

        self.memo_fetch: Dict[CanonicalName, Future[Project]] = {}
        self.memo_version_metadata: Dict[ProjectVersion, Future[BasicMetadata]] = {}

        self.queue: deque[Tuple[Choice, CanonicalName, Requirement, str]] = deque()
        self.current_version_callback = current_version_callback
        self.known_conflicts: Set[CanonicalName] = set()

    def feed_file(self, req_file: Path) -> None:
        for req in _iter_simple_requirements(req_file):
            self.feed(req, str(req_file))

    def feed(self, req: Requirement, source: str = "arg") -> None:
        name = CanonicalName(canonicalize_name(req.name))
        LOG.info("Feed %s (%r) from %s", name, str(req), source)
        if name not in self.memo_fetch:
            self.memo_fetch[name] = self.pool.submit(self._fetch_project, name, False)

        self.queue.append((self.root, name, req, source))

    @ktrace("project_name", "proactive", shortname=True)
    def _fetch_project(self, project_name: CanonicalName, proactive: bool) -> Project:
        project_page = self.pypi_simple.get_project_page(project_name)
        project = Project.from_pypi_simple_project_page(project_page)
        # It's extremely likely that we will subsequently look up the deps of
        # the most recent version, so go ahead and schedule the metadata fetch.
        if project.versions:
            latest_version_key = max(project.versions)
            latest_version = project.versions[latest_version_key]

            if latest_version not in self.memo_version_metadata:
                self.memo_version_metadata[latest_version] = self.pool.submit(
                    self._fetch_project_metadata, project_name, latest_version
                )

        LOG.debug("_fetch_project done %s", project_name)
        return project

    @ktrace("project_name", "version.version", shortname=True)
    def _fetch_project_metadata(
        self, project_name: CanonicalName, version: ProjectVersion
    ) -> BasicMetadata:
        md = version.get_deps(
            self.pypi_simple, self.uncached_session, self.extracted_metadata_cache
        )
        # It's extremely likely that we will subsequently look up the deps of
        # this version, so go ahead and schedule that too.  (But not with any
        # extras.)
        with kev("prefetch"):
            for req in md.reqs:
                name = CanonicalName(canonicalize_name(req.name))
                if name not in self.memo_fetch and self.env_markers.match(req.marker):
                    self.memo_fetch[name] = self.pool.submit(
                        self._fetch_project, name, True
                    )

        LOG.debug("_fetch_project_metadata done %s %s", project_name, version)
        return md

    def drain(self) -> None:
        chosen: Dict[CanonicalName, LooseVersion] = {}

        while self.queue:
            (parent, name, req, source) = self.queue.popleft()
            LOG.info(
                "process %s %s from %s with extras %s", name, req, source, req.extras
            )
            fut = self.memo_fetch[name]
            if hasattr(self.pool, "bump"):
                self.pool.bump(fut)
            with kev("project result", project_name=name):
                project = fut.result()

            cur = chosen.get(name)
            version = find_best_compatible_version(
                project,
                req,
                self.env_markers,
                cur,
                self.current_version_callback,
            )
            choice = Choice(name, version)
            edge = Edge(
                choice, specifier=req.specifier, markers=req.marker, note=source
            )
            parent.deps.append(edge)

            if cur and cur != version:
                LOG.warning("Multiple versions for %s: %s and %s", name, cur, version)
                self.known_conflicts.add(name)
            chosen[name] = version

            if t := project.versions.get(version):
                if t not in self.memo_version_metadata:
                    fut2 = self.pool.submit(self._fetch_project_metadata, name, t)
                    self.memo_version_metadata[t] = fut2
                else:
                    fut2 = self.memo_version_metadata[t]

                if hasattr(self.pool, "bump"):
                    self.pool.bump(fut2)
                with kev("ver result", project_name=name, project_version=str(version)):
                    md = fut2.result()
                for r in md.reqs:
                    r_name = CanonicalName(canonicalize_name(r.name))
                    LOG.info(
                        "  drain possible requirement %s -> %s (%s)", name, r_name, r
                    )
                    if self.env_markers.match(r.marker, sorted(req.extras)):
                        if r_name not in self.memo_fetch:
                            fut = self.pool.submit(self._fetch_project, r_name, False)
                            self.memo_fetch[r_name] = fut

                        self.queue.append((choice, r_name, r, "dep"))
                        LOG.info("    keep")
                    else:
                        LOG.info("    omit")

    def print_flat(
        self,
        choice: Optional[Choice] = None,
        seen: Optional[
            Set[Tuple[CanonicalName, LooseVersion, Optional[Tuple[str, ...]]]]
        ] = None,
    ) -> None:
        if choice is None:
            choice = self.root
            seen = set()

        assert seen is not None
        # Simple recursive postorder
        for x in choice.deps:
            key = (x.target.project, x.target.version, x.target.extras)
            flag = key in seen
            seen.add(key)

            if x.target.deps:
                self.print_flat(x.target, seen)
            dep_extras = f"[{', '.join(x.target.extras)}]" if x.target.extras else ""
            if not flag:
                print(f"{x.target.project}{dep_extras}=={x.target.version}")

    def print_tree(
        self,
        choice: Optional[Choice] = None,
        seen: Optional[
            Set[Tuple[CanonicalName, LooseVersion, Optional[Tuple[str, ...]]]]
        ] = None,
        known_conflicts: Set[CanonicalName] = set(),
        depth: int = 0,
    ) -> None:
        prefix = ". " * depth
        if choice is None:
            choice = self.root
            seen = set()
            known_conflicts = self.known_conflicts

        assert seen is not None
        # Inorder, but avoid doing duplicate work...
        for x in choice.deps:
            # TODO display whether install or build dep, and whether pin disallows
            # current version, has compatible bdist, no sdist, etc
            key = (x.target.project, x.target.version, x.target.extras)
            dep_extras = (
                f"[{', '.join(sorted(x.target.extras))}]" if x.target.extras else ""
            )
            if key in seen:
                click.echo(
                    prefix
                    + click.style(
                        x.target.project,
                        fg="magenta"
                        if key[0] in known_conflicts and x.specifier
                        else None,
                    )
                    + f"{dep_extras} (=={x.target.version}) (already listed){' ; ' + str(x.markers) if x.markers else ''} via "
                    + click.style(x.specifier or "*", fg="yellow")
                )
            else:
                if key[0] in known_conflicts:
                    # conflicting decision
                    color = "magenta"
                else:
                    cur = self.current_version_callback(x.target.project)
                    if cur and Version(cur) == x.target.version:
                        color = "cyan"
                    else:
                        color = "green"
                    # color = "red" if not x.target.has_sdist else "green"
                seen.add(key)
                click.echo(
                    prefix
                    + click.style(
                        x.target.project,
                        fg=color,
                    )
                    + f"{dep_extras} (=={x.target.version}){' ; ' + str(x.markers) if x.markers else ''} via "
                    + click.style(x.specifier or "*", fg="yellow")
                )
                #     + click.style(" no whl" if not x.target.has_bdist else "", fg="blue")
                # )
                if x.target.deps:
                    self.print_tree(x.target, seen, known_conflicts, depth + 1)
