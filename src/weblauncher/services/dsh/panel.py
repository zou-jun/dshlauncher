"""更新面板：本地 HTTP 页，展示可更新项并触发升级。"""

from __future__ import annotations

import contextlib
import hmac
import json
import secrets
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ... import browser
from . import service, updates
from .upgrade import BusyError, UpgradeError, UpgradeJob, UpgradeManager

_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>DeepSeek Harness 更新</title>
<style>
:root{color-scheme:dark;--bg:#0f1115;--card:#171b22;--line:#2a303b;--fg:#e8e8ea;
      --muted:#9aa3b2;--accent:#6ea8ff;--ok:#53c68a;--warn:#e6b450;--err:#f06a6a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:14px/1.55 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:980px;margin:0 auto;padding:26px 22px 60px}
header{display:flex;align-items:flex-start;gap:16px;justify-content:space-between;margin-bottom:20px}
h1{font-size:21px;margin:0 0 4px;font-weight:650}
h2{font-size:15px;margin:0 0 12px;font-weight:600}
.sub{color:var(--muted);font-size:13px}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;border:1px solid var(--line);
      color:var(--muted);font-size:12px;white-space:nowrap}
.pill.ok{color:var(--ok);border-color:#24543c}
.pill.warn{color:var(--warn);border-color:#5a4722}
.pill.err{color:var(--err);border-color:#5c2a2a}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;
      margin-bottom:16px}
.row{display:flex;align-items:center;gap:12px;justify-content:space-between;flex-wrap:wrap}
.versions{font-size:16px;font-variant-numeric:tabular-nums}
.arrow{color:var(--muted);margin:0 4px}
.muted{color:var(--muted)}
.small{font-size:12px}
button{border:1px solid var(--line);background:#202631;color:var(--fg);border-radius:8px;
       padding:7px 13px;font:inherit;cursor:pointer}
button:hover:not(:disabled){border-color:#3d4656;background:#262d3a}
button.primary{background:#2c5da8;border-color:#3a6fbd}
button.primary:hover:not(:disabled){background:#346abc}
button.danger{color:#ffb4b4;border-color:#5c2a2a}
button:disabled{opacity:.45;cursor:not-allowed}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:middle}
th{color:var(--muted);font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:0}
td.name{font-weight:550}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.badge{display:inline-block;padding:1px 7px;border-radius:6px;font-size:11px;
       background:#252b36;color:var(--muted)}
.badge.update{background:#20375c;color:#9ec4ff}
.badge.pinned{background:#4a3a1c;color:#f0c879}
.badge.missing,.badge.unsupported{background:#392626;color:#e6a0a0}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
pre.log{max-height:290px;overflow:auto;background:#0b0d11;border:1px solid var(--line);
        border-radius:8px;padding:10px 12px;font-size:12px;white-space:pre-wrap;word-break:break-word}
.steps{list-style:none;padding:0;margin:0 0 12px}
.steps li{display:flex;gap:8px;align-items:baseline;padding:3px 0}
.dot{width:8px;height:8px;border-radius:50%;background:#4b5565;flex:0 0 8px;margin-top:6px}
.dot.ok{background:var(--ok)}.dot.failed{background:var(--err)}
.dot.running{background:var(--accent)}.dot.skipped{background:var(--muted)}
.toolbar{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.hidden{display:none}
.error-box{border-color:#5c2a2a;color:#ffb4b4}
@media(max-width:640px){th.optional,td.optional{display:none}}
</style></head>
<body><main>
<header>
  <div>
    <h1>DeepSeek Harness 更新</h1>
    <div class="sub" id="subtitle">正在检查…</div>
  </div>
  <div class="toolbar">
    <button id="refresh">重新检查</button>
    <button id="upgrade-all" class="primary" disabled>全部升级</button>
  </div>
</header>

<div id="notice" class="card hidden"></div>

<div id="dsh-card" class="card">
  <div class="row">
    <div>
      <h2>dsh 运行时</h2>
      <div class="versions" id="dsh-version">—</div>
      <div class="small muted" id="dsh-detail"></div>
    </div>
    <button id="dsh-upgrade" class="primary" disabled>升级 dsh</button>
  </div>
</div>

<div class="card">
  <div class="row" style="margin-bottom:10px">
    <h2 style="margin:0">插件 <span class="muted small" id="profile-label"></span></h2>
    <span class="small muted" id="plugin-summary"></span>
  </div>
  <table>
    <thead><tr><th>名称</th><th>当前</th><th>最新</th>
      <th class="optional">说明</th><th style="width:92px"></th></tr></thead>
    <tbody id="plugins"></tbody>
  </table>
</div>

<div id="unsupported-card" class="card hidden">
  <h2>跳过项</h2>
  <div id="unsupported" class="small muted"></div>
</div>

<div id="job-card" class="card hidden">
  <div class="row" style="margin-bottom:10px">
    <h2 style="margin:0">升级进度</h2>
    <span class="pill" id="job-status">—</span>
  </div>
  <ul class="steps" id="job-steps"></ul>
  <pre class="log" id="job-log"></pre>
</div>

<div id="errors-card" class="card hidden error-box">
  <h2>检查问题</h2>
  <div id="errors" class="small"></div>
</div>
</main>
<script>
const base = location.pathname.replace(/[/]+$/, "");
const token = base.split("/").pop();
const $ = (id) => document.getElementById(id);
const state = { report: null, job: null, jobBusy: false };

async function api(path, options = {}) {
  const headers = Object.assign({"X-Panel-Token": token}, options.headers || {});
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(base + path, Object.assign({cache: "no-store"}, options, {headers}));
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || ("HTTP " + response.status));
  return data;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function versionRow(current, latest) {
  const wrap = el("span", "versions");
  wrap.append(el("span", "", current || "—"), el("span", "arrow", "→"), el("span", "", latest || "—"));
  return wrap;
}

function stateBadge(plugin) {
  const map = {update: "可更新", pinned: "锁定", current: "最新", missing: "未安装", unsupported: "跳过"};
  const cls = plugin.state === "update" ? "update" : plugin.state === "pinned" ? "pinned"
    : plugin.state === "current" ? "" : plugin.state;
  return el("span", "badge " + cls, map[plugin.state] || plugin.state);
}

function allTargets() {
  const targets = [];
  const report = state.report;
  if (!report) return targets;
  if (report.dsh.update_available && report.dsh.upgrade_supported) targets.push("dsh");
  for (const plugin of report.profile.plugins || []) {
    if (plugin.update_available) targets.push("plugin:" + plugin.name);
  }
  return targets;
}

function render() {
  const report = state.report;
  if (!report) return;
  const dsh = report.dsh;
  const profile = report.profile;
  const busy = state.jobBusy;

  $("subtitle").textContent = "检查于 " + report.checked_at +
    " · " + report.update_count + " 项可更新 · 服务" +
    (state.service && state.service.running ? "运行中" : "未运行");

  const notice = $("notice");
  notice.classList.add("hidden");
  if (dsh.error || profile.error) {
    notice.classList.remove("hidden");
    notice.classList.add("error-box");
    notice.textContent = [
      dsh.error ? "dsh: " + dsh.error : "",
      profile.error ? "profile: " + profile.error : "",
    ].filter(Boolean).join("  ");
  }

  $("dsh-card").classList.toggle("hidden", !dsh.current && !dsh.error);
  $("dsh-version").replaceChildren(versionRow(dsh.current, dsh.latest));
  $("dsh-detail").textContent = dsh.update_available
    ? (dsh.detail || "建议先升级 dsh，再升级插件")
    : (dsh.error ? "无法检查" : "已是最新");
  const dshButton = $("dsh-upgrade");
  dshButton.disabled = busy || !dsh.update_available || !dsh.upgrade_supported;
  dshButton.textContent = dsh.error
    ? "无法检查"
    : dsh.update_available
      ? (dsh.upgrade_supported ? "升级 dsh" : "需手动升级")
      : "已是最新";
  dshButton.onclick = () => startUpgrade(["dsh"]);

  $("profile-label").textContent = profile.name + (profile.dir ? " · " + profile.dir : "");
  const plugins = profile.plugins || [];
  const updatesCount = plugins.filter(p => p.update_available).length;
  $("plugin-summary").textContent = profile.error ? "检查失败"
    : (profile.total + " 个插件，" + updatesCount + " 个可更新");

  const tbody = $("plugins");
  tbody.replaceChildren();
  for (const plugin of plugins) {
    const tr = el("tr");
    const name = el("td", "name");
    name.append(el("div", "", plugin.name));
    name.append(el("div", "small muted", plugin.spec));
    const current = el("td", "num", plugin.current || "—");
    const latest = el("td", "num", plugin.latest || "—");
    const detail = el("td", "optional small muted", plugin.detail || "");
    const action = el("td");
    const button = el("button", "", plugin.update_available ? "升级" : stateBadge(plugin).textContent);
    button.disabled = busy || !plugin.update_available;
    if (plugin.update_available) button.onclick = () => startUpgrade(["plugin:" + plugin.name]);
    action.append(button);
    tr.append(name, current, latest, detail, action);
    tbody.append(tr);
  }

  const unsupported = plugins.filter(p => p.state === "unsupported" || p.state === "missing");
  $("unsupported-card").classList.toggle("hidden", unsupported.length === 0);
  const unsupportedBox = $("unsupported");
  unsupportedBox.replaceChildren();
  for (const plugin of unsupported) {
    const row = el("div", "", plugin.name + " · " + plugin.detail);
    unsupportedBox.append(row);
  }

  const all = allTargets();
  const allButton = $("upgrade-all");
  allButton.disabled = busy || all.length === 0;
  allButton.textContent = all.length ? ("全部升级 (" + all.length + ")") : "全部升级";

  const errors = report.errors || [];
  $("errors-card").classList.toggle("hidden", errors.length === 0);
  $("errors").replaceChildren(...errors.map(e => el("div", "", e)));
  renderJob();
}

function renderJob() {
  const job = state.job;
  const card = $("job-card");
  if (!job || job.status === "idle") { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");
  const statusMap = {running: "进行中", succeeded: "已完成", partial: "部分完成", failed: "失败"};
  const pill = $("job-status");
  pill.textContent = statusMap[job.status] || job.status;
  pill.className = "pill " + (job.status === "succeeded" ? "ok"
    : job.status === "running" ? "" : job.status === "partial" ? "warn" : "err");

  const steps = $("job-steps");
  steps.replaceChildren();
  for (const step of job.steps || []) {
    const li = el("li");
    li.append(el("span", "dot " + step.status), el("span", "", step.label +
      (step.detail ? " — " + step.detail : "")));
    steps.append(li);
  }
  const log = $("job-log");
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  log.textContent = (job.log || []).join("\\n");
  if (atBottom) log.scrollTop = log.scrollHeight;
}

async function load(refresh = false) {
  $("refresh").disabled = true;
  $("subtitle").textContent = "正在检查…";
  try {
    const [report, job, service] = await Promise.all([
      api("/api/updates" + (refresh ? "?refresh=1" : "")),
      api("/api/job"),
      api("/api/service"),
    ]);
    state.report = report;
    state.job = job;
    state.service = service;
    state.jobBusy = job && job.status === "running";
    render();
    if (state.jobBusy) poll();
  } catch (error) {
    const notice = $("notice");
    notice.classList.remove("hidden");
    notice.classList.add("error-box");
    notice.textContent = "检查失败：" + error.message;
  } finally {
    $("refresh").disabled = false;
  }
}

async function startUpgrade(targets) {
  if (!targets.length) return;
  const label = targets.length === 1 ? targets[0] : (targets.length + " 项");
  if (!confirm("升级 " + label + "？\\n\\n升级前会停止 dsh 服务，完成后自动重启。")) return;
  state.jobBusy = true;
  render();
  try {
    state.job = await api("/api/upgrade", {method: "POST", body: JSON.stringify({targets})});
    renderJob();
    poll();
  } catch (error) {
    state.jobBusy = false;
    render();
    alert("无法开始升级：" + error.message);
  }
}

async function poll() {
  try {
    state.job = await api("/api/job");
    const running = state.job && state.job.status === "running";
    state.jobBusy = running;
    render();
    if (running) {
      setTimeout(poll, 1000);
    } else {
      await load(true);
    }
  } catch (error) {
    state.jobBusy = false;
    render();
  }
}

$("refresh").onclick = () => load(true);
$("upgrade-all").onclick = () => {
  const targets = allTargets();
  if (!targets.length) return;
  startUpgrade(targets);
};
load(false);
</script></body></html>"""


class _PanelHttpd(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    panel: PanelServer


class _Handler(BaseHTTPRequestHandler):
    server: _PanelHttpd  # type: ignore[assignment]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - 基类签名
        pass

    def _base(self) -> str:
        return "/" + self.server.panel.token

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if content_type.startswith("text/html"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:",
            )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: Any) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def do_GET(self) -> None:  # noqa: N802 - http.server 接口
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return
        parsed = urlsplit(self.path)
        base = self._base()
        path = parsed.path
        try:
            if path in {base, base + "/"}:
                self._send(200, _PAGE.encode(), "text/html; charset=utf-8")
            elif path == base + "/api/updates":
                refresh = parse_qs(parsed.query).get("refresh", ["0"])[0] == "1"
                self._json(200, self.server.panel.check(refresh=refresh).as_dict())
            elif path == base + "/api/job":
                job = self.server.panel.job
                self._json(200, job.as_dict() if job is not None else {"status": "idle"})
            elif path == base + "/api/service":
                self._json(200, self.server.panel.service_status())
            else:
                self._json(404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - 面板必须把失败显示出来
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self) -> None:  # noqa: N802 - http.server 接口
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return
        path = urlsplit(self.path).path
        if path != self._base() + "/api/upgrade":
            self._json(404, {"error": "not found"})
            return
        origin = (self.headers.get("Origin") or "").strip()
        expected = f"http://127.0.0.1:{self.server.server_address[1]}"
        if origin and origin != expected:
            self._json(403, {"error": "forbidden origin"})
            return
        token = self.headers.get("X-Panel-Token") or ""
        if not hmac.compare_digest(token.encode(), self.server.panel.token.encode()):
            self._json(403, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "invalid content length"})
            return
        if length <= 0 or length > 65536:
            self._json(400, {"error": "invalid body"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "invalid json"})
            return
        raw_targets = payload.get("targets") if isinstance(payload, dict) else None
        if not isinstance(raw_targets, list) or not all(isinstance(item, str) for item in raw_targets):
            self._json(400, {"error": "targets 必须是字符串数组"})
            return
        targets = list(raw_targets)
        try:
            report = self.server.panel.check()
            job = self.server.panel.manager.start(targets, report)
        except BusyError as exc:
            self._json(409, {"error": str(exc)})
        except (UpgradeError, ValueError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - 面板必须把失败显示出来
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
        else:
            self._json(202, job)


class PanelServer:
    """只在启动器进程存活期间存在的本地更新面板。"""

    def __init__(
        self,
        context,
        *,
        profile: str = service.WEB_PROFILE,
        timeout: float = updates.DEFAULT_TIMEOUT,
        exclusive: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.context = context
        self.profile = profile
        self.timeout = timeout
        self.token = secrets.token_hex(16)
        self._check_lock = threading.Lock()
        self._report: updates.UpdateReport | None = None
        self._report_at = 0.0
        self._closed = False
        self.manager = UpgradeManager(context, exclusive=exclusive)
        httpd = _PanelHttpd(("127.0.0.1", 0), _Handler)
        httpd.panel = self
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self._thread = threading.Thread(target=httpd.serve_forever, name="dsh-updates-panel", daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/{self.token}/"

    @property
    def job(self) -> UpgradeJob | None:
        return self.manager.job

    def start(self) -> None:
        self._thread.start()

    def check(self, *, refresh: bool = False) -> updates.UpdateReport:
        with self._check_lock:
            fresh = self._report is not None and time.monotonic() - self._report_at < 20.0
            if refresh or not fresh:
                self._report = updates.check(
                    self.context.settings,
                    profile=self.profile,
                    timeout=self.timeout,
                )
                self._report_at = time.monotonic()
            assert self._report is not None
            return self._report

    def service_status(self) -> dict[str, Any]:
        return self.context.service().status(check_ports=False).as_dict()

    def open_window(self) -> str:
        panel_settings = replace(
            self.context.settings,
            profile_dir=self.context.paths.panel_profile,
            dedupe=True,
        )
        return browser.launch(panel_settings, self.url, backend=self.context.backend)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._httpd.shutdown()
        self._httpd.server_close()


def run(
    context,
    *,
    profile: str = service.WEB_PROFILE,
    timeout: float = updates.DEFAULT_TIMEOUT,
) -> int:
    """前台运行面板：CLI ``updates --panel``。Ctrl+C 结束。"""
    panel = PanelServer(context, profile=profile, timeout=timeout)
    panel.start()
    if sys.stdout is not None:
        with contextlib.suppress(OSError):
            print(panel.url, flush=True)
    try:
        panel.open_window()
    except Exception:
        panel.close()
        raise
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        panel.close()
    return 0
