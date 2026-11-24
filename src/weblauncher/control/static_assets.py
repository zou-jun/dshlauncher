"""静态资源读取：只允许 webui/static 下的路径。"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "webui" / "static"


class StaticAssetError(FileNotFoundError):
    """请求路径越出静态资源根目录。"""


def read(name: str) -> bytes:
    root = STATIC.resolve()
    path = (STATIC / name).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise StaticAssetError(name) from exc
    return path.read_bytes()


__all__ = ["STATIC", "StaticAssetError", "read"]
