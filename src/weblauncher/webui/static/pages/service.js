import {
  state, esc, api, shell, pageHead, breadcrumb, serviceTabs, servicePath, serviceIcon,
} from "../core.js";
import { pill } from "./status.js";
import { loadLogs } from "./logs.js";

export async function loadService(id) {
  const target = servicePath(id);
  const service = await api(`/api/services/${encodeURIComponent(id)}`);
  if (state.route !== target) return;
  state.service = service;
  state.logService = id;
  renderService(service);
  loadLogs(id, 40).catch(() => {});
}

function renderService(service) {
  const target = servicePath(service.id);
  const root = service.work_dir || service.root_dir;
  const crumbs = breadcrumb([
    { label: "总览", path: "/" },
    { label: service.label, path: servicePath(service.id) },
    { label: "概览" },
  ]);
  shell(`${crumbs}${pageHead(service.label, esc(service.description || service.id), "", serviceIcon(service, "page-icon"))}
    ${serviceTabs(service, "")}
    <div class="card">
      <div class="spread"><h2>服务状态</h2>${pill(service)}</div>
      <div class="grid two">
        <div>
          <div class="stat"><div class="stat-label">进程</div><div class="stat-value">${service.running ? `运行中 · PID ${esc(service.pid)}` : "未运行"}${service.busy ? " · 有操作进行中" : ""}</div></div>
          <div class="stat"><div class="stat-label">监听</div><div class="stat-value">${esc(service.host || "—")}:${esc(service.port ?? "—")} · ${service.listening ? "LISTENING" : "closed"}</div></div>
          <div class="stat"><div class="stat-label">URL</div><div class="stat-value mono">${esc(service.url || "—")}</div></div>
          <div class="stat"><div class="stat-label">工作目录</div><div class="stat-value mono">${esc(root || "—")}</div></div>
        </div>
        <div>
          <div class="stat"><div class="stat-label">数据目录</div><div class="stat-value mono">${esc(service.data_dir || "—")}</div></div>
          <div class="stat"><div class="stat-label">日志</div><div class="stat-value mono">${esc(service.log || "—")}</div></div>
          <div class="stat"><div class="stat-label">支持更新</div><div class="stat-value">${service.supports_updates ? "是" : "否"}</div></div>
        </div>
      </div>
      ${service.error ? `<div class="notice" style="margin-top:12px">${esc(service.error)}</div>` : ""}
      ${service.owner ? `<div class="notice warn" style="margin-top:12px">端口被其它进程占用：<span class="mono">${esc(service.owner)}</span></div>` : ""}
      <hr class="sep">
      <div class="row">
        <button class="btn primary" data-act="open" data-service="${esc(service.id)}">打开服务</button>
        ${service.running
          ? `<button class="btn" data-act="stop" data-service="${esc(service.id)}">停止</button>
             <button class="btn" data-act="restart" data-service="${esc(service.id)}">重启</button>
             <button class="btn danger" data-act="stop" data-force="1" data-service="${esc(service.id)}">强制停止</button>`
          : `<button class="btn" data-act="start" data-service="${esc(service.id)}">启动</button>`}
        <button class="btn ghost" data-act="open-data" data-service="${esc(service.id)}">打开数据目录</button>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <div class="spread"><h2>最近日志</h2>
        <a class="btn small ghost" href="#${servicePath(service.id, "logs")}">查看完整日志</a>
      </div>
      <pre class="logbox" id="logbox">${esc(state.logText || "正在读取…")}</pre>
    </div>
    <div class="card" style="margin-top:16px">
      <h2>服务诊断</h2>
      <p class="small muted">依赖、端口和状态文件的详细检查在服务诊断页。</p>
      <a class="btn ghost" href="#${servicePath(service.id, "diagnostics")}">打开服务诊断</a>
    </div>`, target);
}
