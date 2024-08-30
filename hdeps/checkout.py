from pathlib import Path

from typing import List, Tuple

from metadata_please import basic_metadata_from_source_checkout

from packaging.requirements import Requirement


def read_checkout_reqs(path: Path) -> Tuple[str, List[Requirement]]:
    bm = basic_metadata_from_source_checkout(path)
    if not bm.reqs:
        raise ValueError(
            f"Path {path} did not yield any dependencies, and may not not contain a currently-supported static metadata format (or maybe it just has no deps).  Try specifying -r requirements.txt or omitting."
        )
    return (str(path), [Requirement(r) for r in bm.reqs])
