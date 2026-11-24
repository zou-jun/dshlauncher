"""真浏览器 smoke：headless Chromium + CDP 执行控制台 SPA 并等待异步结果。"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weblauncher import discovery, paths  # noqa: E402
from weblauncher.context import Runtime  # noqa: E402
from weblauncher.control.backend import ControlBackend  # noqa: E402
from weblauncher.control.server import ControlServer  # noqa: E402
from weblauncher.controller import ServiceController  # noqa: E402
from weblauncher.tray import ipc  # noqa: E402

CHECKS = (
    ("/#/", ("总览", "最近操作")),
    ("/#/diagnostics", ("启动器诊断", "通用")),
    ("/#/settings", ("启动器设置", "高级 TOML")),
    ("/#/settings/advanced", ("高级 TOML", "保存 TOML")),
    ("/#/services/dsh", ("服务状态", "最近日志")),
    ("/#/services/dsh/logs", ("日志尾部", "概览")),
    ("/#/services/dsh/diagnostics", ("诊断", "依赖")),
    ("/#/services/dsh/settings", ("dsh web 设置", "dsh.port")),
    ("/#/services/jupyter", ("Jupyter Lab", "服务状态")),
    ("/#/services/jupyter/kernels", ("Jupyter 内核", "已安装内核")),
    ("/#/services/jupyter/workdirs", ("Jupyter 工作目录", "最近目录")),
    ("/#/logs/dsh", ("日志尾部", "概览")),
    ("/#/settings/dsh", ("dsh web 设置", "dsh.port")),
    ("/#/doctor", ("启动器诊断", "通用")),
    ("/#/about", ("关于", "版本")),
)
MODULES = (
    "/core.js",
    "/app.js",
    "/pages/overview.js",
    "/pages/service.js",
    "/pages/logs.js",
    "/pages/status.js",
    "/pages/settings.js",
    "/pages/service_settings.js",
    "/pages/updates.js",
    "/pages/jupyter.js",
    "/pages/diagnostics.js",
    "/pages/about.js",
)
ICONS = ("/icons/control.png", "/icons/dsh.png", "/icons/jupyter.png")


class Chrome:
    def __init__(self, browser: discovery.Browser, profile: Path) -> None:
        self.port = _free_port()
        args = [
            str(browser.path),
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ]
        if getattr(os, "geteuid", lambda: 1)() == 0:
            args.insert(1, "--no-sandbox")
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_port(self.port, 15.0)
        except Exception:
            self.close()
            raise RuntimeError("Chrome CDP 端口未就绪") from None

    def ws_url(self) -> str:
        targets = json.loads(_http(f"http://127.0.0.1:{self.port}/json/list"))
        page = next((item for item in targets if item.get("type") == "page"), None)
        if page is None:
            page = json.loads(_http(f"http://127.0.0.1:{self.port}/json/new?about:blank", method="PUT"))
        return str(page["webSocketDebuggerUrl"])

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        profile = str(self.process.args[-2] if self.process.args else "")
        for proc in psutil.process_iter(["pid", "cmdline"]):
            command = " ".join(proc.info.get("cmdline") or [])
            if "weblauncher-smoke-" in command and profile and profile in command:
                with contextlib.suppress(psutil.Error):
                    proc.kill()


class CDP:
    def __init__(self, url: str) -> None:
        parts = urlsplit(url)
        self.sock = socket.create_connection((parts.hostname or "127.0.0.1", parts.port or 80), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {parts.path} HTTP/1.1\r\n"
            f"Host: {parts.hostname}:{parts.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: http://localhost\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        self.reader = self.sock.makefile("rb", buffering=0)
        status = self.reader.readline().decode("latin-1").strip()
        if "101" not in status:
            raise RuntimeError(f"CDP WebSocket 握手失败：{status}")
        while self.reader.readline() not in {b"\r\n", b"\n", b""}:
            pass
        self.next_id = 1

    def call(self, method: str, params: dict | None = None) -> dict:
        request_id = self.next_id
        self.next_id += 1
        self._send(json.dumps({"id": request_id, "method": method, "params": params or {}}).encode())
        while True:
            message = json.loads(self._receive())
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {method}: {message['error']}")
                return message.get("result", {})

    def evaluate(self, expression: str):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in result:
            raise RuntimeError(f"页面 JS 失败：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def _send(self, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))
        header.extend(mask)
        header.extend(bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)))
        self.sock.sendall(header)

    def _receive(self) -> str:
        first, second = self._read(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]
        masked = bool(second & 0x80)
        mask = self._read(4) if masked else b""
        payload = self._read(length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 0x8:
            raise RuntimeError("CDP WebSocket 已关闭")
        if opcode == 0x9:
            self._send_frame(0xA, payload)
            return self._receive()
        return payload.decode("utf-8")

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode, 0x80 | len(payload)])
        header.extend(mask)
        header.extend(bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)))
        self.sock.sendall(header)

    def _read(self, size: int) -> bytes:
        chunks: list[bytes] = []
        while sum(len(chunk) for chunk in chunks) < size:
            chunk = self.reader.read(size - sum(len(chunk) for chunk in chunks))
            if not chunk:
                raise RuntimeError("CDP 连接提前结束")
            chunks.append(chunk)
        return b"".join(chunks)

    def close(self) -> None:
        self.sock.close()


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _http(url: str, *, method: str = "GET") -> bytes:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()


def _wait_port(port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _http(f"http://127.0.0.1:{port}/json/version")
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Chrome CDP 端口未就绪")


def _wait_text(page: CDP, marks: tuple[str, ...], timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = str(page.evaluate("document.body ? document.body.innerText : ''"))
        if all(mark in text for mark in marks):
            return text
        time.sleep(0.2)
    raise RuntimeError(f"页面未渲染 {marks!r}")


class Console:
    def __init__(self, args: argparse.Namespace, temp: Path) -> None:
        self.temp = temp
        self.server: ControlServer | None = None
        self.process: subprocess.Popen | None = None
        self.paths = paths.Paths(temp / "home")
        if args.exe:
            self._start_packaged(Path(args.exe))
        else:
            runtime = Runtime.create(
                paths_=self.paths,
                backend=SimpleNamespace(),
                migrate=False,
            )
            controllers = {context.service_id: ServiceController(context) for context in runtime.contexts()}
            self.server = ControlServer(ControlBackend(runtime, controllers))
            self.server.start()

    def _start_packaged(self, exe: Path) -> None:
        exe = exe.resolve()
        env = os.environ.copy()
        env["WEBLAUNCHER_HOME"] = str(self.paths.data)
        env["WEBLAUNCHER_BROWSER"] = str(self.temp / "missing-browser.exe")
        env["WEBLAUNCHER_DEDUPE"] = "false"
        self.process = subprocess.Popen(
            [str(exe), "tray"],
            cwd=str(exe.parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def url(self, target: str) -> str:
        if self.server is not None:
            return self.server.bootstrap_url(target)
        assert self.process is not None
        return ipc.send_ui(self.paths, timeout=30.0, wait=20.0, target=target)

    def close(self) -> None:
        if self.server is not None:
            self.server.close()
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self.process.wait(5)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用 headless Chromium 跑控制台页面 smoke")
    parser.add_argument("--browser", help="Chromium 系浏览器可执行文件；默认自动发现")
    parser.add_argument("--timeout", type=float, default=30.0, help="单个页面的等待秒数")
    parser.add_argument("--exe", help="测试打包版：启动该 exe 的 tray 并通过 IPC 取入口")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        browser = discovery.browser_exe(args.browser)
    except discovery.DiscoveryError as exc:
        raise SystemExit(f"smoke 无法启动：{exc}") from exc
    temp = Path(tempfile.mkdtemp(prefix="weblauncher-smoke-"))
    console = Console(args, temp)
    try:
        chrome = Chrome(browser, temp / "profile")
        try:
            page = CDP(chrome.ws_url())
            try:
                page.call("Page.enable")
                for target, markers in CHECKS:
                    page.call("Page.navigate", {"url": console.url(target)})
                    _wait_text(page, markers, args.timeout)
                    print(f"PASS {target} via {browser.family}")
                if sys.platform == "win32":
                    page.call("Page.navigate", {"url": console.url("/#/services/jupyter/workdirs")})
                    _wait_text(page, ("Jupyter 工作目录",), args.timeout)
                    page.evaluate("document.querySelector('[data-workdir-picker]')?.click()")
                    _wait_text(page, ("起始位置",), args.timeout)
                    picker_path = page.evaluate("document.querySelector('#picker-path')?.value")
                    drives = page.evaluate(
                        "[...document.querySelectorAll('[data-pick-path]')]"
                        ".map((node) => node.dataset.pickPath)"
                    )
                    if picker_path != "" or not drives:
                        raise SystemExit(
                            f"工作目录选择器没有从盘符开始：path={picker_path!r} drives={drives!r}"
                        )
                    print("PASS 工作目录选择器从盘符开始")
                modules = page.evaluate(
                    "Promise.all("
                    f"{json.dumps(list(MODULES))}.map(async (path) => [path, (await fetch(path)).status]))"
                )
                bad = [row for row in modules if row[1] != 200]
                if bad:
                    raise SystemExit(f"smoke 模块失败：{bad}")
                print(f"PASS {len(modules)} static modules via CDP")
                icon_rows = page.evaluate(
                    "Promise.all("
                    f"{json.dumps(list(ICONS))}.map(async (path) => [path, (await fetch(path)).status]))"
                )
                bad_icons = [row for row in icon_rows if row[1] != 200]
                if bad_icons:
                    raise SystemExit(f"smoke 图标失败：{bad_icons}")
                print(f"PASS {len(icon_rows)} app icons via CDP")
            finally:
                page.close()
        finally:
            chrome.close()
    finally:
        console.close()
        shutil.rmtree(temp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
