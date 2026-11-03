from dshlauncher.geometry import Rect, needs_fix, preferred_rect

WORK = Rect(0, 0, 2048, 1104)


def test_preferred_is_centered_fraction() -> None:
    assert preferred_rect(WORK) == Rect(164, 77, 1720, 949)


def test_preferred_respects_work_area_offset() -> None:
    work = Rect(1920, 0, 1920, 1040)
    rect = preferred_rect(work)
    assert rect.x >= work.x
    assert rect.right <= work.right
    assert rect.bottom <= work.bottom


def test_preferred_clamps_on_small_screen() -> None:
    work = Rect(0, 0, 1024, 700)
    rect = preferred_rect(work)
    assert rect.width <= work.width - 40
    assert rect.height <= work.height - 40
    assert rect.width > 0 and rect.height > 0


def test_narrow_tall_window_needs_fix() -> None:
    assert needs_fix(Rect(0, 0, 995, 1078), WORK) is True


def test_good_window_is_left_alone() -> None:
    assert needs_fix(Rect(164, 77, 1720, 950), WORK) is False


def test_window_hanging_off_screen_needs_fix() -> None:
    assert needs_fix(Rect(386, 141, 1720, 950), WORK) is True
