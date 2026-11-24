from pathlib import Path

from weblauncher.services.dsh.service import is_dsh_cmdline


def test_matches_bin_js_path() -> None:
    assert is_dsh_cmdline("node /usr/lib/node_modules/@deepseek-ai/dsh/lib/bin.js web --no-open")


def test_matches_path_shim() -> None:
    assert is_dsh_cmdline("node /home/zj/.local/bin/dsh web --no-open")


def test_matches_quoted_windows_shim() -> None:
    assert is_dsh_cmdline(r'"C:\Users\zj\AppData\Roaming\npm\dsh.cmd" web --no-open')


def test_rejects_web_script_next_to_dsh_like_name() -> None:
    assert not is_dsh_cmdline("node C:/tools/dsh web.js")


def test_rejects_other_web_servers() -> None:
    assert not is_dsh_cmdline("python -m http.server 8000")
    assert not is_dsh_cmdline("node /srv/other/web.js")


def test_rejects_non_web_dsh() -> None:
    assert not is_dsh_cmdline("node /home/zj/.local/bin/dsh doctor")


def test_explicit_bin_js_path_is_owned(tmp_path: Path) -> None:
    from weblauncher.services.dsh.adapter import DshAdapter
    from weblauncher.services.dsh.settings import Settings

    bin_js = tmp_path / "harness" / "lib" / "bin.js"
    adapter = DshAdapter(Settings(dsh_bin=bin_js, work_dir=tmp_path))
    cmdline = f'node "{bin_js}" web --no-open'
    assert adapter.owns_process(cmdline)
