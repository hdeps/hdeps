import logging
import threading
import time
from pathlib import Path
from typing import Dict, IO, List, Optional

import click
import keke

from indexurl import get_index_url
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from pypi_simple import ACCEPT_JSON_PREFERRED, PyPISimple

from .markers import EnvironmentMarkers
from .resolution import Walker
from .session import get_cached_retry_session, get_retry_session
from .types import CanonicalName


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
    help="Enable verbose logging (specify multiple times for more)",
    count=True,
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
    verbose: bool,
    parallelism: int,
    have: List[str],
    requirements_file: List[str],
    deps: List[str],
    platform: Optional[str],
    python_version: Optional[str],
    install_order: bool,
) -> None:
    if trace:
        ctx.with_resource(keke.TraceOutput(trace))
    if verbose == 0:
        level = logging.WARNING
    elif verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)-15s %(levelname)-8s %(name)s:%(lineno)s %(message)s",
    )
    if stats:
        threading.Thread(target=_stats_thread, daemon=True).start()

    cached_session = get_cached_retry_session()
    uncached_session = get_retry_session()

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
            get_index_url(), session=cached_session, accept=ACCEPT_JSON_PREFERRED
        ),
        uncached_session=uncached_session,
        current_version_callback=have_versions.get,
    )

    for dep in deps:
        walker.feed(Requirement(dep))
    for req in requirements_file:
        walker.feed_file(Path(req))

    walker.drain()
    if install_order:
        walker.print_flat()
    else:
        walker.print_tree()


if __name__ == "__main__":
    main()
