from dshlauncher.service import is_dsh_cmdline


def test_matches_bin_js_path() -> None:
    assert is_dsh_cmdline("node /usr/lib/node_modules/@deepseek-ai/dsh/lib/bin.js web --no-open")


def test_matches_path_shim() -> None:
    assert is_dsh_cmdline("node /home/zj/.local/bin/dsh web --no-open")


def test_rejects_other_web_servers() -> None:
    assert not is_dsh_cmdline("python -m http.server 8000")
    assert not is_dsh_cmdline("node /srv/other/web.js")


def test_rejects_non_web_dsh() -> None:
    assert not is_dsh_cmdline("node /home/zj/.local/bin/dsh doctor")
