import { state, esc, api, shell, pageHead, empty, servicePath, serviceIcon } from "../core.js";
import { pill } from "./status.js";

export async function loadOverview() {
  const [services, jobs] = await Promise.all([api("/api/services"), api("/api/jobs")]);
  if (state.route !== "/") return;
  state.services = services.services || [];
  state.jobs = jobs.jobs || [];
  const cards = state.services.map(serviceCard).join("");
  const jobRows = state.jobs.slice(0, 6).map((job) => `<div class="stat">
    <div class="spread"><strong>${esc(job.label)}</strong><span class="pill ${job.status === "failed" ? "err" : job.status === "succeeded" ? "ok" : "busy"}">${esc(job.status)}</span></div>
    <div class="small muted">${job.error ? esc(job.error) : esc(job.result || "执行中…")}</div>
  </div>`).join("");
  shell(`${pageHead("总览", "所有本地服务的状态、入口和动作。控制台只监听 127.0.0.1。",
    `<button class="btn primary" data-act="start" data-service="all">启动全部</button>
     <button class="btn" data-act="stop" data-service="all">停止全部</button>
     <button class="btn ghost" data-refresh="overview">刷新</button>`)}
    <div class="grid two">${cards || empty("没有可用服务")}</div>
    <div class="card" style="margin-top:16px"><h2>最近操作</h2>${jobRows || empty("还没有通过控制台执行的操作")}</div>`,
    "/");
}

function serviceCard(service) {
  const url = service.url ? `<div class="meta-value mono">${esc(service.url)}</div>` : `<div class="meta-value muted">未运行</div>`;
  const root = service.work_dir || service.root_dir;
  const unavailable = Boolean(service.error);
  return `<article class="card service-card">
    <div class="service-top"><div>
      <div class="service-title">${serviceIcon(service)}<span class="dot ${service.running ? "ok" : ""}"></span>${esc(service.label)}</div>
      <div class="service-desc">${esc(service.description || service.id)}</div>
    </div>${pill(service)}</div>
    <div class="service-meta">
      <div><div class="meta-label">PID</div><div class="meta-value">${esc(service.pid ?? "—")}</div></div>
      <div><div class="meta-label">端口</div><div class="meta-value">${esc(service.host || "—")}:${esc(service.port ?? "—")}</div></div>
      <div style="grid-column:1/-1"><div class="meta-label">URL</div>${url}</div>
      <div style="grid-column:1/-1"><div class="meta-label">工作目录</div><div class="meta-value mono">${esc(root || "—")}</div></div>
    </div>
    ${service.error ? `<div class="notice small">${esc(service.error)}</div>` : ""}
    ${unavailable ? `<div class="card-actions"><span class="small muted">修正配置后刷新</span></div>` : `
    <div class="card-actions">
      <a class="btn primary" href="#${servicePath(service.id)}">进入服务</a>
      <button class="btn" data-act="open" data-service="${esc(service.id)}">打开</button>
      ${service.running
        ? `<button class="btn" data-act="stop" data-service="${esc(service.id)}">停止</button>
           <button class="btn" data-act="restart" data-service="${esc(service.id)}">重启</button>`
        : `<button class="btn" data-act="start" data-service="${esc(service.id)}">启动</button>`}
    </div>`}
  </article>`;
}
