import sys
from dataclasses import asdict, dataclass, replace
from typing import Optional, Sequence

from packaging.markers import Marker


@dataclass
class EnvironmentMarkers:
    os_name: str = "posix"
    sys_platform: str = "linux"
    platform_machine: str = "x86_64"
    platform_python_implementation: str = "CPython"
    platform_release: Optional[str] = None
    platform_system: str = "Linux"
    platform_version: Optional[str] = None
    python_version: Optional[str] = None
    python_full_version: Optional[str] = None
    implementation_name: str = "cpython"

    def __post_init__(self) -> None:
        if self.sys_platform == "linux":
            if self.python_version and self.python_version[:1] == "2":
                self.sys_platform = "linux2"
        elif self.sys_platform == "win32":
            self.platform_system = "Windows"
            self.os_name = "nt"
        elif self.sys_platform == "darwin":
            self.platform_system = "Darwin"
        else:
            raise TypeError(f"Unknown sys_platform: {self.sys_platform!r}")

    def match(self, marker: Optional[Marker], extras: Sequence[str] = ()) -> bool:
        env = asdict(self)
        if marker:
            if extras:
                if not any(marker.evaluate(dict(env, extra=e)) for e in extras):
                    return False
            else:
                if not marker.evaluate(env):
                    return False
        return True

    @classmethod
    def from_args(
        cls, python_version: Optional[str], sys_platform: Optional[str]
    ) -> "EnvironmentMarkers":
        if python_version:
            if python_version.count(".") == 1:
                python_version += ".0"
        else:
            python_version = ".".join(str(v) for v in sys.version_info[:3])

        obj = cls(
            python_version=python_version.rsplit(".", 1)[0],
            python_full_version=python_version,
        )
        if sys_platform:
            obj = replace(obj, sys_platform=sys_platform)
        return obj
