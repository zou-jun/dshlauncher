"""内置图标资源：控制台、dsh、Jupyter 各自可定位。"""

from __future__ import annotations

import pytest

from weblauncher import icons


def test_each_app_has_bundled_png_and_ico() -> None:
    for name in icons.NAMES:
        assert icons.path(name, ".png") is not None
        assert icons.path(name, ".ico") is not None
        assert icons.read(name)


def test_unknown_icon_is_rejected() -> None:
    with pytest.raises(KeyError):
        icons.path("missing", ".png")
