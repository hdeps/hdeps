import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, IO, List, Optional

import click
import keke

from indexurl import get_index_url
from indexurl.core import DEFAULT_INDEX_URL
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from pypi_simple import ACCEPT_JSON_PREFERRED, PyPISimple
from vmodule import vmodule_init

from .cache import NoCache, SimpleCache
from .markers import EnvironmentMarkers
from .resolution import Walker
from .session import get_cached_retry_session, get_retry_session
from .types import CanonicalName

LOG = logging.getLogger(__name__)


def _stats_thread() -> None:
    prev_ts = None
    prev_process_time = None
    while True:
        ts = time.time()
        process_time = time.process_time()
        if prev_ts is not None:
            keke.kcount(
                "proc_cpu_pct",
                100 * (process_time - prev_process_time) / (ts - prev_ts),
            )

        prev_ts = ts
        prev_process_time = process_time
        time.sleep(0.1)


@click.command()
@click.pass_context
@click.option(
    "--trace", type=click.File("w"), help="Write chrome trace to this filename"
)
@click.option("--stats", is_flag=True, help="Include cpu stats in the trace")
@click.option(
    "--verbose",
    "-v",
    type=int,
    help="Enable verbose logging (default=WARNING, 0=INFO, 1=VLOG_1, 10=DEBUG)",
)
@click.option(
    "--vmodule",
    help="Enable verbose logging only for some explicitly named loggers (e.g. "
    "'hdeps.resolution=1' would enable VLOG_1 for just that one logger.  Comma-separated.",
)
@click.option(
    "-I",
    "--isolate-env",
    is_flag=True,
    help="Isolate from the user's environment (use default index url).",
)
@click.option(
    "--no-cache",
    is_flag=True,
    help="Do not read or write cache for dependencies.",
)
@click.option(
    "--parallelism",
    "-p",
    default=24,
    type=int,
    help="Parallelism factor for network i/o",
)
@click.option(
    "--platform",
    metavar="PLAT",
    default="linux",
    show_default=True,
    help="Optionally override platform: linux, win32, darwin.",
)
@click.option(
    "--python-version",
    metavar="VERSION",
    help="Optionally override python version.  Default is autodetect running.",
)
@click.option(
    "--install-order",
    is_flag=True,
    help="Output a theoretical install order instead of a tree",
)
@click.option(
    "--print-legend",
    is_flag=True,
    help="Output the meaning of colors in a header",
)
@click.option(
    "--color/--no-color",
    is_flag=True,
    default=None,
    help="Default is to guess from NO_COLOR or FORCE_COLOR env vars being non-empty",
)
@click.option("--have", help="pkg==ver to assume already installed", multiple=True)
@click.option("-r", "--requirements-file", multiple=True)
@click.argument(
    "deps",
    nargs=-1,
)
def main(
    ctx: click.Context,
    trace: Optional[IO[str]],
    stats: bool,
    verbose: Optional[int],
    vmodule: Optional[str],
    parallelism: int,
    have: List[str],
    requirements_file: List[str],
    deps: List[str],
    platform: Optional[str],
    python_version: Optional[str],
    install_order: bool,
    isolate_env: bool,
    no_cache: bool,
    print_legend: bool,
    color: Optional[bool],
) -> None:
    if trace:
        ctx.with_resource(keke.TraceOutput(trace))
    vmodule_init(verbose, vmodule)
    if stats:
        threading.Thread(target=_stats_thread, daemon=True).start()

    uncached_session = get_retry_session()
    extracted_metadata_cache: SimpleCache
    if no_cache:
        cached_session = uncached_session
        extracted_metadata_cache = NoCache()
    else:
        cached_session = get_cached_retry_session()
        extracted_metadata_cache = SimpleCache()

    if isolate_env:
        index_url = DEFAULT_INDEX_URL
    else:
        index_url = get_index_url()

    if color is True or (color is None and os.environ.get("FORCE_COLOR")):
        ctx.color = True
    elif color is False or (color is None and os.environ.get("NO_COLOR")):
        ctx.color = False

    have_versions: Dict[CanonicalName, str] = {}
    for h in have:
        k, _, v = h.partition("==")
        have_versions[CanonicalName(canonicalize_name(k))] = v

    walker = Walker(
        parallelism,
        env_markers=EnvironmentMarkers.from_args(
            python_version=python_version, sys_platform=platform
        ),
        pypi_simple=PyPISimple(
            index_url, session=cached_session, accept=ACCEPT_JSON_PREFERRED
        ),
        uncached_session=uncached_session,
        current_version_callback=have_versions.get,
        extracted_metadata_cache=extracted_metadata_cache,
        color=ctx.color,
    )

    def solve() -> None:
        for dep in deps:
            walker.feed(Requirement(dep))
        for req in requirements_file:
            walker.feed_file(Path(req))
        walker.drain()

    solve()

    if install_order:
        walker.print_flat()
    else:
        if print_legend:
            walker.print_legend()
        walker.print_tree()

    click.echo("========== Summary ==========")
    if walker.known_conflicts:
        resolutions: List[Requirement] = []
        for project, versions in walker.known_conflicts.copy().items():
            click.echo(
                f"Found conflict: {project} {sorted([str(x) for x in versions])}"
            )
            for version in versions:
                with keke.kev("pin_attempt", project=project, version=version):
                    LOG.info("Trying to pin %s==%s", project, version)
                    req = Requirement(f"{project}=={version}")
                    walker.clear()
                    # Add the pin as first requirement to see if it can be used
                    # by all subsequent dependencies.
                    walker.feed(req)
                    solve()
                if project not in walker.known_conflicts:
                    resolutions.append(req)
                    break

        if resolutions:
            click.echo("Pin these project versions to resolve conflict:")
            for resolution in resolutions:
                click.echo(resolution)

        unresolved = walker.known_conflicts.keys() - {x.name for x in resolutions}
        if unresolved:
            click.echo("Failed to resolve following conflicts:")
            for conflict in sorted(unresolved):
                click.echo(
                    f"{conflict} {sorted([str(x) for x in walker.known_conflicts[conflict]])}"
                )
    else:
        click.echo("No conflicts found.")


if __name__ == "__main__":
    main()
