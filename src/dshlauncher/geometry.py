"""纯几何计算：默认窗口矩形与"是否需要纠正"的判定（无平台依赖，可单测）。"""

from __future__ import annotations

from typing import NamedTuple

#: dsh 是「侧栏 + 主区 + 右栏」三栏布局：窗口太窄或太方都会显得挤。
WIDTH_RATIO = 0.84
HEIGHT_RATIO = 0.86
MIN_WIDTH = 1024
MIN_HEIGHT = 680
#: 与工作区边缘至少留这么多像素，避免压到任务栏/屏幕边框。
MARGIN = 40
#: 比这更小的窗口视为"比例有问题"，启动时纠正。
MIN_RATIO = 0.6
TOLERANCE = 8


class Rect(NamedTuple):
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


def preferred_rect(
    work: Rect,
    *,
    width_ratio: float = WIDTH_RATIO,
    height_ratio: float = HEIGHT_RATIO,
    min_width: int = MIN_WIDTH,
    min_height: int = MIN_HEIGHT,
    margin: int = MARGIN,
) -> Rect:
    """按工作区比例算一个居中的默认窗口。"""
    max_width = max(320, work.width - margin)
    max_height = max(240, work.height - margin)
    width = min(max(int(work.width * width_ratio), min_width), max_width)
    height = min(max(int(work.height * height_ratio), min_height), max_height)
    return Rect(work.x + (work.width - width) // 2, work.y + (work.height - height) // 2, width, height)


def needs_fix(
    rect: Rect,
    work: Rect,
    *,
    min_ratio: float = MIN_RATIO,
    tolerance: int = TOLERANCE,
) -> bool:
    """窗口过小或超出工作区才纠正；用户自己调过的尺寸不动。"""
    too_small = rect.width < work.width * min_ratio or rect.height < work.height * min_ratio
    off_screen = (
        rect.x < work.x - tolerance
        or rect.y < work.y - tolerance
        or rect.right > work.right + tolerance
        or rect.bottom > work.bottom + tolerance
    )
    return too_small or off_screen
