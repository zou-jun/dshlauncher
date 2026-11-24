import {
  state, esc, api, shell, pageHead, empty, breadcrumb, serviceTabs, servicePath,
  waitForJob,
} from "../core.js";

export function doctorTable(rows) {
  return `<div class="table-wrap"><table><tbody>${(rows || []).map((row) =>
    `<tr><td>${esc(row.name)}</td><td class="mono">${esc(row.value)}</td></tr>`).join("") ||
    `<tr><td class="muted">没有诊断数据</td></tr>`}</tbody></table></div>`;
}

function loadingPage(crumbs, title, subtitle, tabs = "") {
  return `${crumbs}${pageHead(title, subtitle, "")}${tabs}
    <div class="card"><div class="empty">检查中，请稍候…</div></div>`;
}

async function submitDiagnostics(services) {
  const submitted = await api("/api/doctor", { method: "POST", body: { services } });
  return waitForJob(submitted.id);
}

export async function loadLauncherDiagnostics() {
  const target = "/diagnostics";
  const crumbs = breadcrumb([{ label: "总览", path: "/" }, { label: "诊断" }]);
  shell(loadingPage(crumbs, "启动器诊断", "正在检查启动器环境…"), target);
  try {
    const job = await submitDiagnostics([]);
    if (state.route !== target) return;
    if (job.status === "failed") throw new Error(job.error || "诊断失败");
    const data = job.result;
    state.doctor = data;
    shell(`${crumbs}${pageHead("启动器诊断", "启动器自身的平台、Python、浏览器和运行时环境。",
      `<button class="btn ghost" data-refresh="diagnostics">重新检查</button>
       <button class="btn" data-copy-doctor="1">复制 JSON</button>`)}
      <div class="card"><h2>通用</h2>${doctorTable(data.general)}</div>`, target);
  } catch (error) {
    if (state.route !== target) return;
    shell(`${crumbs}${pageHead("启动器诊断", "诊断执行失败。",
      `<button class="btn ghost" data-refresh="diagnostics">重新检查</button>`)}
      <div class="card notice"><strong>加载失败</strong><div class="small" style="margin-top:6px">${esc(error.message)}</div></div>`,
      target);
  }
}

export async function loadServiceDiagnostics(id) {
  const target = servicePath(id, "diagnostics");
  const service = await api(`/api/services/${encodeURIComponent(id)}`);
  if (state.route !== target) return;
  state.service = service;
  const crumbs = breadcrumb([
    { label: "总览", path: "/" },
    { label: service.label, path: servicePath(id) },
    { label: "诊断" },
  ]);
  shell(loadingPage(crumbs, `${service.label} 诊断`, "正在检查服务依赖和端口…", serviceTabs(service, "diagnostics")), target);
  try {
    const job = await submitDiagnostics([id]);
    if (state.route !== target) return;
    if (job.status === "failed") throw new Error(job.error || "诊断失败");
    const data = job.result;
    state.doctor = data;
    const selected = (data.services || []).find((item) => item.id === id);
    const rows = selected?.rows || [];
    shell(`${crumbs}${pageHead(`${service.label} 诊断`, "该服务的依赖、端口、状态文件和日志。",
      `<button class="btn ghost" data-refresh="service-diagnostics" data-service="${esc(id)}">重新检查</button>
       <button class="btn" data-copy-doctor="1">复制 JSON</button>`)}
      ${serviceTabs(service, "diagnostics")}
      <div class="card">${rows.length ? doctorTable(rows) : empty("没有该服务的诊断数据")}</div>`, target);
  } catch (error) {
    if (state.route !== target) return;
    shell(`${crumbs}${pageHead(`${service.label} 诊断`, "诊断执行失败。",
      `<button class="btn ghost" data-refresh="service-diagnostics" data-service="${esc(id)}">重新检查</button>`)}
      ${serviceTabs(service, "diagnostics")}
      <div class="card notice"><strong>加载失败</strong><div class="small" style="margin-top:6px">${esc(error.message)}</div></div>`,
      target);
  }
}
