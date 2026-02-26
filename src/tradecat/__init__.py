from __future__ import annotations

from dataclasses import dataclass

try:
    from importlib.metadata import version as _pkg_version
except Exception:  # pragma: no cover
    _pkg_version = None  # type: ignore[assignment]


def _resolve_version() -> str:
    if _pkg_version is None:
        return "0.1.0"
    try:
        return str(_pkg_version("tradecat"))
    except Exception:  # pragma: no cover
        return "0.1.0"


__version__ = _resolve_version()


@dataclass(frozen=True)
class Data:
    """轻量 facade：面向 PyPI 包导入与示例。"""


@dataclass(frozen=True)
class Indicators:
    """轻量 facade：面向 PyPI 包导入与示例。"""


@dataclass(frozen=True)
class Signals:
    """轻量 facade：面向 PyPI 包导入与示例。"""


@dataclass(frozen=True)
class AI:
    """轻量 facade：面向 PyPI 包导入与示例。"""


__all__ = [
    "AI",
    "Data",
    "Indicators",
    "Signals",
    "__version__",
]
