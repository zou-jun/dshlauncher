"""平台后端选择：Windows 用完整实现，其余平台用尽力而为的实现。"""

from __future__ import annotations

import sys
from types import ModuleType


def load() -> ModuleType:
    if sys.platform == "win32":
        from . import windows as backend
    else:
        from . import posix as backend
    return backend
