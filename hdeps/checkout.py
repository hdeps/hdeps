import os.path
from pathlib import Path

from typing import List, Tuple

from metadata_please import (
    basic_metadata_from_pep621_checkout,
    basic_metadata_from_setuptools_checkout,
)

from packaging.requirements import Requirement


def read_checkout_reqs(path: Path) -> Tuple[str, List[Requirement]]:
    try:
        bm = basic_metadata_from_pep621_checkout(path)
    except OSError:
        pass
    else:
        if bm.reqs:
            return (
                os.path.join(path, "pyproject.toml"),
                [Requirement(req) for req in bm.reqs],
            )

    try:
        bm = basic_metadata_from_setuptools_checkout(path)
    except OSError:
        pass
    else:
        if bm.reqs:
            return (
                os.path.join(path, "setup.cfg"),
                [Requirement(req) for req in bm.reqs],
            )

    raise ValueError(
        f"Path {path} does not contain a currently-supported static metadata.  Try specifying -r requirements.txt"
    )
