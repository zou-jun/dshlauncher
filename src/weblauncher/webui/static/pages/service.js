import { state, esc, api, shell, pageHead } from "../core.js";
import { pill } from "./status.js";
import { loadLogs } from "./logs.js";

export async function loadService(id) {
  const service = await api(`/api/services/${encodeURIComponent(id)}`);
  if (state.route !== `/services/${id}`) return;
  state.service = service;
  state.logService = id;
  renderService(service);
  loadLogs(id);
}

function renderService(service) {
  const settings = service.settings || {};
  const extra = Object.entries(service).filter(([key]) => key.startsWith("kernel") || key === "base_url")
    .map(([key, value]) => `<div class="k">${esc(key)}</div><div class="v">${esc(value)}</div>`).join("");
  const rows = (service.doctor || []).map((row) => `<tr><td>${esc(row.name)}</td><td class="mono">${esc(row.value)}</td></tr>`).join("");
  const links = (service.links || []).map((link) =>
    `<a class="btn ghost" href="${esc(link.href)}">${esc(link.label)}</a>`).join("");
  shell(`${pageHead(service.label, `${esc(service.id)} · ${esc(service.description || "")}`,
    `${links}<a class="btn ghost" href="#/">返回总览</a>
     <button class="btn ghost" data-refresh="service" data-service="${esc(service.id)}">刷新</button>`)}
    <div class="card" id="svc-status">
      <div class="spread"><h2>${esc(service.label)}</h2>${pill(service)}</div>
      <div class="grid two">
        <div>
          <div class="stat"><div class="stat-label">进程</div><div class="stat-value">${service.running ? `运行中 · PID ${esc(service.pid)}` : "未运行"}${service.busy ? " · 有操作进行中" : ""}</div></div>
          <div class="stat"><div class="stat-label">监听</div><div class="stat-value">${esc(service.host || "—")}:${esc(service.port ?? "—")} · ${service.listening ? "LISTENING" : "closed"}</div></div>
          <div class="stat"><div class="stat-label">URL</div><div class="stat-value mono">${esc(service.url || "—")}</div></div>
          <div class="stat"><div class="stat-label">工作目录</div><div class="stat-value mono">${esc(service.work_dir || "—")}</div></div>
        </div>
        <div>
          <div class="stat"><div class="stat-label">数据目录</div><div class="stat-value mono">${esc(service.data_dir || "—")}</div></div>
          <div class="stat"><div class="stat-label">日志</div><div class="stat-value mono" id="logpath">${esc(service.log || "—")}</div></div>
          ${extra}
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
        <a class="btn ghost" href="#/logs/${encodeURIComponent(service.id)}">查看完整日志</a>
        <button class="btn ghost" data-act="open-data" data-service="${esc(service.id)}">打开数据目录</button>
      </div>
    </div>
    <div class="grid two" style="margin-top:16px">
      <div class="card"><div class="spread"><h2>实时日志</h2><div class="row">
        <button class="btn small ghost" data-refresh="logs" data-service="${esc(service.id)}">刷新</button>
        <a class="btn small ghost" href="#/logs/${encodeURIComponent(service.id)}">完整日志</a>
      </div></div>
        <pre class="logbox" id="logbox">${esc(state.logText || "正在读取…")}</pre>
      </div>
      <div class="card"><h2>服务诊断</h2>
        <div class="table-wrap"><table><tbody>${rows || `<tr><td class="muted">暂无诊断数据</td></tr>`}</tbody></table></div>
      </div>
    </div>
    <div class="card" style="margin-top:16px"><h2>生效设置</h2>
      <div class="kv">${Object.entries(settings).map(([key, value]) => `<div class="k">${esc(key)}</div><div class="v mono">${esc(value)}</div>`).join("")}</div>
      <div class="small muted" style="margin-top:10px">更改持久配置请前往 <a href="#/settings" style="color:var(--accent)">设置</a>；运行中的服务需要重启后生效。</div>
    </div>`,
    `/services/${service.id}`);
}
