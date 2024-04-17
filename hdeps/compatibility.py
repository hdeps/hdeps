import functools
import logging
from typing import Dict, List, Optional, Tuple

from keke import kev

from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version
from vmodule import VLOG_1, VLOG_2

from .markers import EnvironmentMarkers
from .projects import Project
from .types import VersionCallback

LOG = logging.getLogger(__name__)


class NoMatchingRelease(Exception):
    pass


def requires_python_match(
    project: Project, cache: Dict[str, bool], python_version: Version, v: Version
) -> bool:
    pv = project.versions[v]
    if not pv.requires_python:
        return True
    if (verdict := cache.get(pv.requires_python)) is not None:
        return verdict
    try:
        specifier_set = SpecifierSet(pv.requires_python)
        verdict = python_version in specifier_set
    except InvalidSpecifier as e:
        LOG.debug(
            "Ignore %s==%s has invalid requires_python %r but including anyway",
            project.name,
            v,
            e,
        )
        verdict = True
    cache[pv.requires_python] = verdict
    return verdict


def find_best_compatible_version(
    project: Project,
    req: Requirement,
    env_markers: EnvironmentMarkers,
    already_chosen: Optional[Version],
    current_version_callback: VersionCallback,
) -> Version:
    # Handle requires_python first, so we can produce a better error message
    # when there are no version-compatible candidates (before we even get to
    # req.specifier)
    python_version_str = env_markers.python_full_version
    assert python_version_str is not None
    python_version = Version(python_version_str)

    _requires_python_match = functools.partial(
        requires_python_match, project, {}, python_version
    )

    possible: List[Version] = []

    specifier_matched = False
    with kev("reverse"):
        rev = reversed(project.versions.keys())
    with kev("initial filter"):
        for version in req.specifier.filter(rev):
            specifier_matched = True
            if _requires_python_match(version):
                # Only keep the first one
                possible.append(version)
                break

    # If the current version is a non-public version, we need to add it back
    # here.
    with kev("current_version_callback"):
        cur = current_version_callback(project.name)
    cur_v: Optional[Version] = None
    if cur:
        cur_v = Version(cur)
        # Allow the current version to be a guess -- it doesn't actually have to
        # be compatible with the current version of python.  Filter out if we
        # know for sure.
        if cur_v in project.versions:
            if _requires_python_match(cur_v):
                possible.append(cur_v)
        else:
            # Non-public version, assume it's ok
            possible.append(cur_v)
    LOG.log(VLOG_2, "Callback %s -> %s", cur, cur_v)

    if already_chosen:
        possible.append(already_chosen)

    if not possible:
        if specifier_matched:
            raise NoMatchingRelease(
                f"{project.name} has no {python_version}-compatible release"
            )
        else:
            raise NoMatchingRelease(
                f"{project.name} has no release matching {req.specifier}"
            )

    # The documentation for SepcifierSet.filter notes that it handles the logic
    # for whether to include prereleases, so we don't need that here.
    LOG.log(VLOG_1, "possible for %s: %s", req, possible)
    with kev("filter by specifier"):
        # This should only ever be ~3 items now!
        possible = list(req.specifier.filter(possible))
    if not possible:
        if not list(req.specifier.filter(project.versions.keys())):
            # Referencing the dragon above, if we had a current version and it was
            # unsuitable, then we still output a generic message.  Note that > does not
            # set the prerelease bit, but >= does.
            raise NoMatchingRelease(
                f"{project.name} has no release with constraint {req.specifier}"
            )
        else:
            raise NoMatchingRelease(
                f"{project.name} has no {python_version}-compatible release with constraint {req.specifier}"
            )

    # TODO: yanked support

    # The sort key is
    # ( matches_already_chosen: bool,
    #   matches_current_version: bool,
    #   recency_index: int,
    #   version: Version )
    # so that after sorting the last item is the "best" one.

    with kev("final sort"):
        xform_possible: List[Tuple[bool, bool, int, Version]] = sorted(
            (p == already_chosen, p == cur_v, i, p) for (i, p) in enumerate(possible)
        )

    LOG.log(VLOG_1, "Sorted %s", project.name)
    for el in xform_possible:
        LOG.log(VLOG_1, "%s", el)
    return xform_possible[-1][3]
