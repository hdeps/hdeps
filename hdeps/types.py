from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, NewType, Optional, Tuple

from packaging.markers import Marker
from packaging.specifiers import SpecifierSet
from packaging.version import Version

CanonicalName = NewType("CanonicalName", str)
VersionCallback = Callable[[CanonicalName], Optional[str]]

ChoiceKeyType = Tuple[CanonicalName, Version, Tuple[str, ...]]


@dataclass
class Choice:
    project: CanonicalName = field(repr=True)
    version: Version = field(repr=True)
    # TODO extras should be normalized, thus CanonicalName
    extras: Tuple[str, ...] = field(default_factory=tuple)
    deps: List[Edge] = field(default_factory=list)
    has_sdist: bool = False
    has_wheel: bool = False

    def key(self) -> ChoiceKeyType:
        return (self.project, self.version, self.extras)


@dataclass
class Edge:
    target: Choice = field(repr=True)
    specifier: Optional[SpecifierSet]
    markers: Optional[Marker]
    note: Optional[str]
