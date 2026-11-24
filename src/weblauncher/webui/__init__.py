"""Web 控制台静态资源（无构建 SPA）。"""

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"

__all__ = ["STATIC_DIR"]
