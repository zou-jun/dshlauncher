import { api, state, esc, toast, shell, pageHead, errorCard, waitForJob } from "../core.js";

export async function loadUpdates(refresh = false) {
  const profile = sessionStorage.getItem("updates.profile") || "web";
  const timeout = sessionStorage.getItem("updates.timeout") || "30";
  shell(`${pageHead("dsh 更新", "正在检查 dsh 与插件版本…", "")}
    <div class="card"><div class="empty">检查中，请稍候…</div></div>`, "/updates");
  try {
    const submitted = await api("/api/updates", {
      method: "POST",
      body: { profile, timeout: Number(timeout), refresh },
    });
    const checked = await waitForJob(submitted.id);
    if (state.route !== "/updates") return;
    if (checked.status === "failed") throw new Error(checked.error || "检查更新失败");
    state.updates = checked.result;
    let job = { status: "idle" };
    try { job = await api("/api/upgrade-job"); } catch (error) {}
    state.upgradeJob = job;
    renderUpdates(profile, timeout);
  } catch (error) {
    if (state.route !== "/updates") return;
    toast(error.message, "err");
    shell(`${pageHead("dsh 更新", "检查更新失败。", `<button class="btn ghost" data-updates-refresh="1">重新检查</button>`)}
      ${errorCard(error)}`, "/updates");
  }
}

function renderUpdates(profile, timeout) {
  const report = state.updates;
  if (!report) return;
  const dsh = report.dsh || {};
  const profileData = report.profile || { plugins: [] };
  const plugins = profileData.plugins || [];
  const allTargets = [];
  if (dsh.update_available && dsh.upgrade_supported) allTargets.push("dsh");
  for (const plugin of plugins) if (plugin.update_available) allTargets.push("plugin:" + plugin.name);
  const pluginRows = plugins.map((plugin) => {
    const badge = plugin.update_available
      ? `<span class="badge update">可更新</span>`
      : plugin.state === "pinned" ? `<span class="badge pinned">锁定</span>`
      : plugin.state === "missing" || plugin.state === "unsupported" ? `<span class="badge missing">${esc(plugin.state)}</span>`
      : "";
    const action = plugin.update_available
      ? `<button class="btn small primary" data-upgrade="plugin:${esc(plugin.name)}">升级</button>`
      : badge;
    return `<tr><td><strong>${esc(plugin.name)}</strong><div class="tiny muted mono">${esc(plugin.spec)}</div></td>
      <td class="mono">${esc(plugin.current || "—")}</td><td class="mono">${esc(plugin.latest || "—")}</td>
      <td class="small muted">${esc(plugin.detail || "")}</td><td class="actions">${action}</td></tr>`;
  }).join("");
  const dshError = dsh.error ? `<div class="notice" style="margin-top:10px">${esc(dsh.error)}</div>` : "";
  const job = state.upgradeJob || { status: "idle" };
  const jobHtml = job.status && job.status !== "idle" ? `<div class="card" style="margin-top:16px">
      <div class="spread"><h2>升级进度</h2><span class="pill ${job.status === "succeeded" ? "ok" : job.status === "failed" ? "err" : "busy"}">${esc(job.status)}</span></div>
      <ol class="steps">${(job.steps || []).map((step) => `<li><span class="sdot ${esc(step.status)}"></span><span>${esc(step.label)}${step.detail ? ` — ${esc(step.detail)}` : ""}</span></li>`).join("")}</ol>
      <pre class="logbox" style="margin-top:10px">${esc((job.log || []).join("\n") || "等待输出…")}</pre>
    </div>` : "";
  shell(`${pageHead("dsh 更新", `检查于 ${esc(report.checked_at || "—")} · ${report.update_count || 0} 项可更新`,
    `<a class="btn ghost" href="#/">返回总览</a>
     <button class="btn ghost" data-updates-refresh="1">重新检查</button>
     <button class="btn primary" data-upgrade-all="1" ${allTargets.length ? "" : "disabled"}>全部升级 (${allTargets.length})</button>`)}
    <div class="card"><div class="form-row">
      <label class="field"><span>dsh profile</span><input id="updates-profile" value="${esc(profile)}"></label>
      <label class="field"><span>单次查询超时（秒）</span><input id="updates-timeout" type="number" min="5" max="300" value="${esc(timeout)}"></label>
      <button class="btn" data-updates-refresh="1">应用并检查</button>
    </div><div class="small muted" style="margin-top:9px">升级前会停止 dsh；完成后尝试重启。升级日志追加到 <span class="mono">upgrades.log</span>。</div></div>
    <div class="card" style="margin-top:16px"><div class="spread"><h2>dsh 运行时</h2>
      ${dsh.update_available && dsh.upgrade_supported ? `<button class="btn primary" data-upgrade="dsh">升级 dsh</button>` : `<span class="pill">${dsh.error ? "无法检查" : dsh.update_available ? "需手动升级" : "已是最新"}</span>`}</div>
      <div class="mono" style="font-size:16px">${esc(dsh.current || "—")} <span class="muted">→</span> ${esc(dsh.latest || "—")}</div>
      <div class="small muted" style="margin-top:5px">${esc(dsh.detail || dsh.install || "")}</div>${dshError}</div>
    <div class="card" style="margin-top:16px"><div class="spread"><h2>插件 <span class="tiny muted">${esc(profileData.name || profile)} · ${esc(profileData.dir || "")}</span></h2>
      <span class="small muted">${plugins.length} 个 · ${plugins.filter((p) => p.update_available).length} 个可更新</span></div>
      <div class="table-wrap"><table><thead><tr><th>名称</th><th>当前</th><th>最新</th><th>说明</th><th></th></tr></thead><tbody>${pluginRows || `<tr><td colspan="5" class="muted">没有插件记录</td></tr>`}</tbody></table></div>
    </div>${(report.errors || []).length ? `<div class="card notice" style="margin-top:16px"><h2>检查问题</h2>${report.errors.map((error) => `<div class="small">${esc(error)}</div>`).join("")}</div>` : ""}
    ${jobHtml}`, "/updates");
}

export async function startUpgrade(targets) {
  if (!targets.length) return;
  if (!confirm(`升级 ${targets.length} 项？升级前会停止 dsh，完成后尝试重启。`)) return;
  const profile = sessionStorage.getItem("updates.profile") || "web";
  const timeout = Number(sessionStorage.getItem("updates.timeout") || 30);
  await api("/api/upgrades", { method: "POST", body: { targets, profile, timeout } });
  toast("升级任务已开始", "ok");
  pollUpgrade();
}

async function pollUpgrade() {
  for (let i = 0; i < 300; i += 1) {
    const job = await api("/api/upgrade-job");
    state.upgradeJob = job;
    if (state.route === "/updates" && state.updates) renderUpdates(sessionStorage.getItem("updates.profile") || "web", sessionStorage.getItem("updates.timeout") || "30");
    if (job.status && !["running", "idle"].includes(job.status)) {
      toast(job.status === "succeeded" ? "升级完成" : "升级结束，请查看进度日志", job.status === "succeeded" ? "ok" : "err");
      if (state.route === "/updates") loadUpdates(true).catch((error) => toast(error.message, "err"));
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

export function buildTargets(report) {
  const targets = [];
  if (report.dsh?.update_available && report.dsh?.upgrade_supported) targets.push("dsh");
  for (const plugin of report.profile?.plugins || []) if (plugin.update_available) targets.push("plugin:" + plugin.name);
  return targets;
}
