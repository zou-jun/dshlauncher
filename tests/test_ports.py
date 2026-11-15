import socket
from collections.abc import Iterator

import pytest

from dshlauncher import ports


@pytest.fixture(autouse=True)
def clean_cache() -> Iterator[None]:
    ports.excluded_ranges.cache_clear()
    yield
    ports.excluded_ranges.cache_clear()


def _listening_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock


def test_free_port() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    verdict = ports.probe("127.0.0.1", port)
    assert verdict.free and verdict.describe() == "可用"


def test_listening_port_is_in_use() -> None:
    sock = _listening_socket()
    try:
        verdict = ports.probe("127.0.0.1", sock.getsockname()[1])
    finally:
        sock.close()
    assert verdict.in_use and verdict.describe() == "被占用"


def test_permission_error_is_reserved(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(host: str, port: int) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(ports, "_bind", denied)
    monkeypatch.setattr(ports, "excluded_ranges", lambda: ((2987, 3086),))

    verdict = ports.probe("127.0.0.1", 3080)
    assert verdict.reserved
    assert verdict.detail == "2987-3086"
    assert verdict.describe() == "系统保留（2987-3086）"


def test_winerror_10013_counts_as_reserved(monkeypatch: pytest.MonkeyPatch) -> None:
    error = OSError(10013, "permission denied")
    error.winerror = 10013  # type: ignore[attr-defined]

    def denied(host: str, port: int) -> None:
        raise error

    monkeypatch.setattr(ports, "_bind", denied)
    monkeypatch.setattr(ports, "excluded_ranges", lambda: ())
    assert ports.probe("127.0.0.1", 3080).reserved


def test_reserved_message_names_range_and_next_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ports, "excluded_ranges", lambda: ((2987, 3086),))
    text = ports.reserved_message("127.0.0.1", 3080)
    assert "3080" in text
    assert "2987-3086" in text
    assert "--port 18080" in text


def test_candidates_prefer_previous_then_configured() -> None:
    assert ports.candidates(18081, 3080)[:4] == (18081, 3080, 18080, 18082)
    assert ports.candidates(None, 18080) == (18080, 18081, 18082, 18083)


def test_ephemeral_zero_is_free_without_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(host: str, port: int) -> None:
        raise AssertionError("port 0 不该尝试 bind")

    monkeypatch.setattr(ports, "_bind", boom)
    assert ports.probe("127.0.0.1", 0).free


def test_excluded_ranges_hides_console(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(args: list[str], **kwargs: object):  # noqa: ANN202 - 测试替身
        calls.append(kwargs)
        return type("R", (), {"stdout": b"2987 3086\n"})()

    monkeypatch.setattr(ports, "sys", type("S", (), {"platform": "win32"})())
    monkeypatch.setattr(ports.subprocess, "run", fake_run)
    assert ports.excluded_ranges() == ((2987, 3086),)
    assert calls[0]["creationflags"] == ports.CREATE_NO_WINDOW
