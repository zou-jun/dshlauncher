import sys

import pytest

from weblauncher import __main__ as cli


class FakeStream:
    """记录 reconfigure 调用；真实的 sys.stdout 在测试里不能被改坏。"""

    def __init__(self) -> None:
        self.encodings: list[str] = []

    def reconfigure(self, *, encoding: str) -> None:
        self.encodings.append(encoding)


def _patch_streams(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeStream, FakeStream]:
    # 必须在测试体里打补丁：pytest 的捕获会在 fixture 之后重新接管 sys.stdout，
    # 在 fixture 里替换的假流会被换掉。
    out, err = FakeStream(), FakeStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    return out, err


def test_utf8_console_gets_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = _patch_streams(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cli, "_console_utf8", lambda: True)

    cli._utf8_streams()

    assert out.encodings == ["utf-8"]
    assert err.encodings == ["utf-8"]


def test_gbk_console_keeps_default_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    # 936 控制台：强制 UTF-8 会让中文变成乱码，必须保持 Python 默认编码。
    out, err = _patch_streams(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cli, "_console_utf8", lambda: False)

    cli._utf8_streams()

    assert out.encodings == []
    assert err.encodings == []


def test_explicit_pythonioencoding_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    out, _ = _patch_streams(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cli, "_console_utf8", lambda: True)
    monkeypatch.setenv("PYTHONIOENCODING", "gbk")

    cli._utf8_streams()

    assert out.encodings == []


def test_pythonutf8_counts_as_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    out, _ = _patch_streams(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(cli, "_console_utf8", lambda: True)
    monkeypatch.setenv("PYTHONUTF8", "1")

    cli._utf8_streams()

    assert out.encodings == []


def test_posix_terminals_are_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    out, _ = _patch_streams(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(cli, "_console_utf8", lambda: False)

    cli._utf8_streams()

    assert out.encodings == ["utf-8"]
