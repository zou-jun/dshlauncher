import { api, state, esc, shell, pageHead, empty, errorCard, waitForJob } from "../core.js";

function doctorTable(rows) {
  return `<div class="table-wrap"><table><tbody>${(rows || []).map((row) =>
    `<tr><td>${esc(row.name)}</td><td class="mono">${esc(row.value)}</td></tr>`).join("") ||
    `<tr><td class="muted">没有诊断数据</td></tr>`}</tbody></table></div>`;
}

export async function loadDoctor() {
  shell(`${pageHead("诊断", "正在检查启动器环境和各服务依赖…", "")}
    <div class="card"><div class="empty">检查中，请稍候…</div></div>`, "/doctor");
  try {
    const submitted = await api("/api/doctor", { method: "POST", body: {} });
    const job = await waitForJob(submitted.id);
    if (state.route !== "/doctor") return;
    if (job.status === "failed") throw new Error(job.error || "诊断失败");
    const data = job.result;
    state.doctor = data;
    const services = (data.services || []).map((service) => `<div class="card">
      <div class="spread"><h2>${esc(service.label)}</h2><a class="btn small ghost" href="#/settings/${encodeURIComponent(service.id)}">设置</a></div>
      ${doctorTable(service.rows)}
    </div>`).join("");
    shell(`${pageHead("诊断", "启动器通用环境与服务各自的依赖、端口和运行时诊断。",
      `<button class="btn ghost" data-refresh="doctor">重新检查</button><button class="btn" data-copy-doctor="1">复制 JSON</button>`)}
      <div class="card"><h2>通用</h2>${doctorTable(data.general)}</div>
      <div class="grid two" style="margin-top:16px">${services || empty("没有服务诊断数据")}</div>`, "/doctor");
  } catch (error) {
    if (state.route !== "/doctor") return;
    shell(`${pageHead("诊断", "诊断执行失败。", `<button class="btn ghost" data-refresh="doctor">重新检查</button>`)}
      ${errorCard(error)}`, "/doctor");
  }
}
