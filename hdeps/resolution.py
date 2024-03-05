import logging
import threading
from collections import defaultdict, deque
from concurrent.futures import Future, ThreadPoolExecutor

from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import click

from keke import kev, ktrace

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from pypi_simple import PyPISimple
from requests.sessions import Session
from vmodule import VLOG_1, VLOG_2

# from tpe_prio import ThreadPoolExecutor

from .cache import SimpleCache

from .compatibility import find_best_compatible_version
from .markers import EnvironmentMarkers
from .projects import BasicMetadata, Project, ProjectVersion
from .requirements import _iter_simple_requirements
from .session import get_retry_session
from .types import CanonicalName, Choice, ChoiceKeyType, Edge, VersionCallback

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
        extracted_metadata_cache: Optional[SimpleCache] = None,
        color: Optional[bool] = None,
    ):
        self.root = Choice(CanonicalName("-"), Version("0"))
        self.pool = ThreadPoolExecutor(max_workers=parallelism)
        self.env_markers = env_markers
        self.pypi_simple = pypi_simple
        self.uncached_session = uncached_session or get_retry_session()
        self.extracted_metadata_cache = extracted_metadata_cache or SimpleCache()
        self.color = color

        self.memo_fetch: Dict[CanonicalName, Future[Project]] = {}
        self.memo_fetch_lock = threading.Lock()
        self.memo_version_metadata: Dict[ProjectVersion, Future[BasicMetadata]] = {}

        self.queue: deque[
            Tuple[Choice, CanonicalName, Requirement, str, Set[ChoiceKeyType]]
        ] = deque()
        self.current_version_callback = current_version_callback
        self.known_conflicts: Dict[CanonicalName, Set[Version]] = defaultdict(set)

    def clear(self) -> None:
        self.root = Choice(CanonicalName("-"), Version("0"))
        self.known_conflicts.clear()

    def feed_file(self, req_file: Path) -> None:
        for req in _iter_simple_requirements(req_file):
            self.feed(req, str(req_file))

    def feed(self, req: Requirement, source: str = "arg") -> None:
        name = CanonicalName(canonicalize_name(req.name))
        LOG.log(VLOG_1, "Feed %s (%r) from %s", name, str(req), source)
        if req.marker and not self.env_markers.match(req.marker):
            return

        with self.memo_fetch_lock:
            if name not in self.memo_fetch:
                self.memo_fetch[name] = self.pool.submit(
                    self._fetch_project, name, False
                )

        empty_set: Set[ChoiceKeyType] = set()
        self.queue.append((self.root, name, req, source, empty_set))

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

        LOG.log(VLOG_1, "_fetch_project done %s", project_name)
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
        with kev("prefetch", count=len(md.reqs)):
            for req in md.reqs:
                name = CanonicalName(canonicalize_name(req.name))
                # Don't bother with markers if we've already scheduled
                if name not in self.memo_fetch:
                    # Marker evaluation is relatively expensive
                    if self.env_markers.match(req.marker):
                        # Check again under the lock (for correctness, and since some time has elapsed)
                        with self.memo_fetch_lock:
                            if name not in self.memo_fetch:
                                self.memo_fetch[name] = self.pool.submit(
                                    self._fetch_project, name, True
                                )

        LOG.log(
            VLOG_1, "_fetch_project_metadata done %s %s", project_name, version.version
        )
        return md

    def drain(self) -> None:
        chosen: Dict[CanonicalName, Version] = {}

        while self.queue:
            (parent, name, req, source, parent_keys) = self.queue.popleft()
            LOG.info(
                "process %s %s from %s with extras %s", name, req, source, req.extras
            )
            fut = self.memo_fetch[name]
            if hasattr(self.pool, "bump"):
                self.pool.bump(fut)
            with kev("project result", project_name=name):
                project = fut.result()

            cur = chosen.get(name)
            with kev("find_best_compatible_version", project_name=name, req=str(req)):
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
            if choice.key() in parent_keys:
                LOG.info("Avoid circular dep processing %s", name)
                continue

            if cur and cur != version:
                LOG.info("Multiple versions for %s: %s and %s", name, cur, version)
                self.known_conflicts[name].update([cur, version])
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

                choice.has_sdist = md.has_sdist
                choice.has_wheel = md.has_wheel
                for r in md.reqs:
                    r_name = CanonicalName(canonicalize_name(r.name))
                    LOG.log(
                        VLOG_2,
                        "  drain possible requirement %s -> %s (%s)",
                        name,
                        r_name,
                        r,
                    )
                    if self.env_markers.match(r.marker, sorted(req.extras)):
                        with self.memo_fetch_lock:
                            if r_name not in self.memo_fetch:
                                fut = self.pool.submit(
                                    self._fetch_project, r_name, False
                                )
                                self.memo_fetch[r_name] = fut

                        self.queue.append(
                            (choice, r_name, r, "dep", parent_keys | {choice.key()})
                        )

                        LOG.log(VLOG_2, "    keep")
                    else:
                        LOG.log(VLOG_2, "    omit")

    def print_flat(
        self,
        choice: Optional[Choice] = None,
        seen: Optional[
            Set[Tuple[CanonicalName, Version, Optional[Tuple[str, ...]]]]
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

    COLORS: Dict[Optional[str], Optional[str]] = {
        "conflict": "magenta",
        "good": "green",
        "have_reuse": "cyan",
        "no_sdist": "red",
        "no_wheel": "blue",
        None: None,
    }

    def print_legend(self) -> None:
        click.echo(
            click.style("[good]", fg=self.COLORS["good"]) + " is what you hope to see."
        )
        click.echo(
            click.style("[conflict]", fg=self.COLORS["conflict"])
            + " means two different versions were found during this walk."
        )
        click.echo(
            click.style("[no_sdist]", fg=self.COLORS["no_sdist"])
            + " means this project does not have an sdist.  (This is something"
            + " to watch out for if you want to build from source.)"
        )
        # This is not a whole-line styling -- omit for now
        # click.echo(
        #     click.style("[no_wheel]", fg=self.COLORS["no_wheel"])
        #     + " means this project does not have a wheel, thus might be missing its deps."
        # )
        click.echo(
            click.style("[have_reuse]", fg=self.COLORS["have_reuse"])
            + " means that a version specified in --have was kept."
        )
        click.echo()

    def print_tree(
        self,
        choice: Optional[Choice] = None,
        seen: Optional[
            Set[Tuple[CanonicalName, Version, Optional[Tuple[str, ...]]]]
        ] = None,
        known_conflicts: Dict[CanonicalName, Set[Version]] = defaultdict(set),
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

            def print_line(color_choice: Optional[str], dep_stuff: Any) -> None:
                click.echo(
                    prefix
                    + click.style(x.target.project, fg=self.COLORS[color_choice])
                    + dep_stuff
                    + (
                        f" [{color_choice}]"
                        # N.b. self.color is intentionally tri-state -- None
                        # being autodetect in click and we assume it will be
                        # enabled thus don't output names here.
                        if color_choice and self.color is False
                        else ""
                    )
                )

            if key in seen:
                print_line(
                    "conflict" if key[0] in known_conflicts and x.specifier else None,
                    f"{dep_extras} (=={x.target.version}) (already listed){' ; ' + str(x.markers) if x.markers else ''} via "
                    + click.style(x.specifier or "*", fg="yellow"),
                )
            else:
                if key[0] in known_conflicts:
                    # conflicting decision
                    color = "conflict"
                else:
                    cur = self.current_version_callback(x.target.project)
                    if cur and Version(cur) == x.target.version:
                        color = "have_reuse"
                    else:
                        color = "no_sdist" if not x.target.has_sdist else "good"
                seen.add(key)

                print_line(
                    color,
                    f"{dep_extras} (=={x.target.version}){' ; ' + str(x.markers) if x.markers else ''} via "
                    + click.style(x.specifier or "*", fg="yellow")
                    + click.style(
                        " no whl" if not x.target.has_wheel else "", fg="blue"
                    ),
                )
                if x.target.deps:
                    self.print_tree(x.target, seen, known_conflicts, depth + 1)
