from dshlauncher.service import parse_url


def test_uses_url_after_latest_start_marker() -> None:
    text = (
        "dsh web: http://127.0.0.1:3080/?token=old\n"
        "[launcher] start port=3080 at=2026-11-03 10:00:00\n"
        "[llm-deepseek-account] model listing loaded\n"
        "\n"
        "[launcher] start port=3080 at=2026-11-03 10:05:00\n"
        "dsh web: http://127.0.0.1:3080/?token=new\n"
    )
    assert parse_url(text) == "http://127.0.0.1:3080/?token=new"


def test_returns_none_before_the_new_process_prints() -> None:
    text = "dsh web: http://127.0.0.1:3080/?token=old\n[launcher] start port=3080\nbooting\n"
    assert parse_url(text) is None


def test_falls_back_without_marker() -> None:
    text = "dsh web: http://127.0.0.1:3080/?token=x\n"
    assert parse_url(text) == "http://127.0.0.1:3080/?token=x"
