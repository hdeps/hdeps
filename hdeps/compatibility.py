import logging
from typing import Dict, List, Optional, Tuple

from keke import kev

from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version
from vmodule import VLOG_1

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

    requires_python_cache: Dict[str, bool] = {}

    def requires_python_match(v: Version) -> bool:
        pv = project.versions[v]
        if not pv.requires_python:
            return True
        if verdict := requires_python_cache.get(pv.requires_python) is not None:
            return verdict
        try:
            specifier_set = SpecifierSet(pv.requires_python)
            verdict = python_version in specifier_set
        except InvalidSpecifier as e:
            LOG.debug(
                "Ignore %s==%s has invalid requires_python %r but including anway",
                project.name,
                v,
                e,
            )
            verdict = True
        requires_python_cache[pv.requires_python] = verdict
        return verdict

    possible: List[Version] = []

    specifier_matched = False
    with kev("reverse"):
        rev = reversed(project.versions.keys())
    with kev("initial filter"):
        for version in req.specifier.filter(rev):
            specifier_matched = True
            if requires_python_match(version):
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
        # Here be dragons: if we already filtered the current version out for
        # requires_python, then don't bother adding it back in; this is only
        # intended for non-public version reuse.
        if cur_v not in project.versions:
            possible.append(cur_v)

    if already_chosen:
        possible.append(already_chosen)

    if not possible:
        if specifier_matched:
            raise ValueError(
                f"{project.name} has no {python_version}-compatible release"
            )
        else:
            raise ValueError(f"{project.name} has no release matching {req.specifier}")

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
            raise ValueError(
                f"{project.name} has no release with constraint {req.specifier}"
            )
        else:
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
