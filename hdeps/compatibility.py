import logging
from typing import Dict, List, Optional, Tuple

from keke import kev

from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from .markers import EnvironmentMarkers
from .projects import Project
from .types import VersionCallback

LOG = logging.getLogger(__name__)


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
    possible: List[Version] = []

    requires_python_cache: Dict[str, bool] = {}

    with kev("filter requires_python"):
        for v, pv in project.versions.items():
            try:
                if pv.requires_python:
                    result = requires_python_cache.get(pv.requires_python)
                    if result is None:
                        ss = SpecifierSet(pv.requires_python)
                        result = python_version in ss
                        requires_python_cache[pv.requires_python] = result
                    if not result:
                        continue
            except InvalidSpecifier as e:
                LOG.debug("Ignore %s==%s because %r", project.name, v, e)
                continue
            possible.append(v)

    # If the current version is a non-public version, we need to add it back
    # here.
    with kev("current_version_callback"):
        cur = current_version_callback(project.name)
    cur_v: Optional[Version] = None
    if cur:
        cur_v = Version(cur)
        # Here be dragons: if we already filtered the current version out for
        # requires_python, then don't bother adding it back in; this is only
        # intended for non-public version reuse.
        if cur_v not in project.versions:
            possible.append(cur_v)

    if not possible:
        raise ValueError(f"{project.name} has no {python_version}-compatible release")

    # The documentation for SepcifierSet.filter notes that it handles the logic
    # for whether to include prereleases, so we don't need that here.
    LOG.debug("possible %s", possible)
    with kev("filter by specifier"):
        possible = list(req.specifier.filter(possible))
    if not possible:
        raise ValueError(
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

    return xform_possible[-1][3]
