const state = {
  meta: null,
  services: [],
  jobs: [],
  route: "/",
  service: null,
  logText: "",
  config: null,
  kernels: [],
  workdirs: null,
  updates: null,
  upgradeJob: null,
  about: null,
  doctor: [],
  timers: new Set(),
};

const app = document.getElementById("app");
const toasts = document.getElementById("toasts");
const modalRoot = document.getElementById("modal-root");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function q(id) { return document.getElementById(id); }
function fmtBool(value) { return value ? "是" : "否"; }
function statusClass(value) {
  return value === "running" ? "ok" : value === "stopped" ? "" : value === "error" ? "err" : "warn";
}
function statusText(service) {
  if (service.error) return "不可用";
  if (service.busy) return "操作中";
  return service.running ? "运行中" : "已停止";
}
function pill(service) {
  return `<span class="pill ${statusClass(service.error ? "error" : service.busy ? "" : service.running ? "running" : "stopped")}">
    <span class="dot ${service.running ? "ok" : service.error ? "err" : ""}"></span>${esc(statusText(service))}</span>`;
}
function toast(message, kind = "") {
  const node = document.createElement("div");
  node.className = "toast " + kind;
  node.textContent = message;
  toasts.append(node);
  setTimeout(() => node.remove(), 5200);
}
function activeNav(path) {
  if (path.startsWith("/services/")) return "/";
  if (path.startsWith("/jupyter")) return "/jupyter";
  return path;
}

async function api(path, options = {}) {
  const headers = Object.assign({ Accept: "application/json" }, options.headers || {});
  if (state.meta) headers["X-CSRF-Token"] = state.meta.csrf;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, Object.assign({ cache: "no-store" }, options, { headers }));
  const type = response.headers.get("Content-Type") || "";
  const data = type.includes("application/json") ? await response.json().catch(() => ({})) : await response.text();
  if (!response.ok) {
    if (response.status === 401) {
      app.innerHTML = `<div class="empty" style="grid-column:1/-1"><h2>控制台会话已失效</h2>
        <p>请从启动器重新打开控制台，或执行 <code>weblauncher ui</code>。</p></div>`;
    }
    throw new Error((data && data.error) || `HTTP ${response.status}`);
  }
  return data;
}

function shell(main, path) {
  const nav = [
    ["/", "▦", "总览"],
    ["/updates", "↑", "更新"],
    ["/jupyter", "◆", "Jupyter"],
    ["/doctor", "✚", "诊断"],
    ["/settings", "⚙", "设置"],
    ["/about", "ⓘ", "关于"],
  ];
  const links = nav.map(([href, icon, label]) => {
    const cls = activeNav(path) === href ? "active" : "";
    return `<a class="${cls}" href="#${href}"><span class="nav-icon">${icon}</span>${label}</a>`;
  }).join("");
  app.innerHTML = `<aside class="sidebar">
    <div class="brand"><div class="brand-mark">W</div><div>
      <div class="brand-name">Web 服务启动器</div>
      <div class="brand-sub">LOCAL CONTROL CENTER</div>
    </div></div>
    <nav class="nav">${links}</nav>
    <div class="sidebar-foot">
      <div><span class="dot ok"></span> 控制台已连接</div>
      <div>v${esc(state.meta?.version || "?")} · 仅本机</div>
    </div>
  </aside><main class="main" id="main"></main>`;
  q("main").innerHTML = main;
}

function pageHead(title, sub, actions = "") {
  return `<div class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<div class="sub">${sub}</div>` : ""}</div>
    <div class="toolbar">${actions}</div></div>`;
}

function errorCard(error) {
  return `<div class="card notice"><strong>加载失败</strong><div class="small" style="margin-top:6px">${esc(error.message || error)}</div></div>`;
}

function empty(text) { return `<div class="empty">${esc(text)}</div>`; }

// ── 总览 ───────────────────────────────────────────────────────────────
async function loadOverview() {
  const [services, jobs] = await Promise.all([api("/api/services"), api("/api/jobs")]);
  state.services = services.services || [];
  state.jobs = jobs.jobs || [];
  state.route = "/";
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
  return `<article class="card service-card">
    <div class="service-top"><div>
      <div class="service-title"><span class="dot ${service.running ? "ok" : ""}"></span>${esc(service.label)}</div>
      <div class="service-desc">${esc(service.description || service.id)}</div>
    </div>${pill(service)}</div>
    <div class="service-meta">
      <div><div class="meta-label">PID</div><div class="meta-value">${esc(service.pid ?? "—")}</div></div>
      <div><div class="meta-label">端口</div><div class="meta-value">${esc(service.host || "—")}:${esc(service.port ?? "—")}</div></div>
      <div style="grid-column:1/-1"><div class="meta-label">URL</div>${url}</div>
      <div style="grid-column:1/-1"><div class="meta-label">工作目录</div><div class="meta-value mono">${esc(root || "—")}</div></div>
    </div>
    ${service.error ? `<div class="notice small">${esc(service.error)}</div>` : ""}
    <div class="card-actions">
      <button class="btn primary" data-act="open" data-service="${esc(service.id)}">打开</button>
      ${service.running
        ? `<button class="btn" data-act="stop" data-service="${esc(service.id)}">停止</button>
           <button class="btn" data-act="restart" data-service="${esc(service.id)}">重启</button>`
        : `<button class="btn" data-act="start" data-service="${esc(service.id)}">启动</button>`}
      <a class="btn ghost" href="#/services/${encodeURIComponent(service.id)}">详情</a>
      <button class="btn ghost small" data-act="open-log" data-service="${esc(service.id)}">日志</button>
    </div>
  </article>`;
}

// ── 服务详情 ───────────────────────────────────────────────────────────
async function loadService(id) {
  const service = await api(`/api/services/${encodeURIComponent(id)}`);
  state.service = service;
  state.route = `/services/${id}`;
  renderService(service);
  loadLogs(id);
}

async function loadLogs(id) {
  try {
    const data = await api(`/api/services/${encodeURIComponent(id)}/logs?tail=300`);
    state.logText = data.text;
    const box = q("logbox");
    if (box) {
      const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
      box.textContent = data.text || "（日志为空）";
      if (atBottom) box.scrollTop = box.scrollHeight;
    }
    const path = q("logpath");
    if (path) path.textContent = data.path;
  } catch (error) { toast(error.message, "err"); }
}

function renderService(service) {
  const settings = service.settings || {};
  const extra = Object.entries(service).filter(([key]) => key.startsWith("kernel") || key === "base_url")
    .map(([key, value]) => `<div class="k">${esc(key)}</div><div class="v">${esc(value)}</div>`).join("");
  const rows = (service.doctor || []).map((row) => `<tr><td>${esc(row.name)}</td><td class="mono">${esc(row.value)}</td></tr>`).join("");
  shell(`${pageHead(service.label, `${esc(service.id)} · ${esc(service.description || "")}`,
    `<a class="btn ghost" href="#/">返回总览</a>
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
        <button class="btn ghost" data-act="open-log" data-service="${esc(service.id)}">打开日志文件</button>
        <button class="btn ghost" data-act="open-data" data-service="${esc(service.id)}">打开数据目录</button>
      </div>
    </div>
    <div class="grid two" style="margin-top:16px">
      <div class="card"><div class="spread"><h2>实时日志</h2><button class="btn small ghost" data-refresh="logs" data-service="${esc(service.id)}">刷新</button></div>
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

// ── 设置 ───────────────────────────────────────────────────────────────
async function loadSettings() {
  const data = await api("/api/config");
  state.config = data;
  const fields = (data.fields || []).map((field) => configField(field, data.values?.[field.key])).join("");
  shell(`${pageHead("设置", `配置文件：<span class="mono">${esc(data.path)}</span>`,
    `<button class="btn ghost" data-refresh="settings">重新读取</button>`)}
    <div class="card"><h2>常用配置</h2>
      <div class="small muted" style="margin-bottom:14px">优先级：命令行 / 环境变量 &gt; <code>config.toml</code> &gt; 默认值。保存后运行中的服务需要重启。</div>
      <div class="form-grid">${fields}</div>
    </div>
    <div class="card" style="margin-top:16px"><h2>高级 TOML</h2>
      <div class="small muted" style="margin-bottom:10px">直接编辑原文件，保存前会做 TOML 校验；注释会原样保留。</div>
      <textarea id="raw-config" spellcheck="false">${esc(data.raw)}</textarea>
      <div class="row" style="margin-top:10px"><button class="btn primary" data-cfg-raw="1">保存 TOML</button>
        <button class="btn ghost" data-refresh="settings">放弃修改</button></div>
    </div>`, "/settings");
}

function configField(field, value) {
  const key = field.key;
  let control = "";
  if (field.type === "boolean") {
    control = `<label class="check"><input type="checkbox" data-cfg-input="${esc(key)}" ${value ? "checked" : ""}> ${esc(field.label)}</label>`;
  } else if (field.type === "select") {
    control = `<select data-cfg-input="${esc(key)}">${(field.choices || []).map((choice) =>
      `<option ${choice === value ? "selected" : ""} value="${esc(choice)}">${esc(choice)}</option>`).join("")}</select>`;
  } else {
    const type = field.type === "number" ? "number" : "text";
    const input = `<input type="${type}" data-cfg-input="${esc(key)}" value="${esc(value ?? "")}">`;
    control = field.type === "path"
      ? `<div class="row"><div class="grow">${input}</div><button class="btn small ghost" data-picker="${esc(key)}">浏览</button></div>`
      : input;
  }
  return `<div class="field"><label class="field"><span>${esc(field.label)} <span class="tiny muted">${esc(key)}</span></span>${control}</label>
    <div class="row"><button class="btn small" data-cfg-save="${esc(key)}">保存</button>
      <button class="btn small ghost" data-cfg-unset="${esc(key)}">删除配置项</button></div>
    ${field.help ? `<span class="tiny muted">${esc(field.help)}</span>` : ""}</div>`;
}

async function saveConfigValue(key) {
  const input = document.querySelector(`[data-cfg-input="${CSS.escape(key)}"]`);
  if (!input) return;
  let value;
  if (input.type === "checkbox") value = input.checked;
  else if (input.type === "number") value = Number(input.value);
  else value = input.value;
  await api("/api/config/value", { method: "PUT", body: { key, value } });
  toast(`${key} 已保存；运行中的服务需重启`, "ok");
}

async function saveRawConfig() {
  const raw = q("raw-config").value;
  await api("/api/config", { method: "PUT", body: { raw } });
  toast("配置已保存；运行中的服务需重启", "ok");
  await loadSettings();
}

// ── 更新 ───────────────────────────────────────────────────────────────
async function loadUpdates(refresh = false) {
  const profile = sessionStorage.getItem("updates.profile") || "web";
  const timeout = sessionStorage.getItem("updates.timeout") || "30";
  const data = await api(`/api/updates?profile=${encodeURIComponent(profile)}&timeout=${encodeURIComponent(timeout)}${refresh ? "&refresh=1" : ""}`);
  state.updates = data;
  let job = { status: "idle" };
  try { job = await api("/api/upgrade-job"); } catch (error) {}
  state.upgradeJob = job;
  renderUpdates(profile, timeout);
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
  shell(`${pageHead("检查与升级", `检查于 ${esc(report.checked_at || "—")} · ${report.update_count || 0} 项可更新`,
    `<button class="btn ghost" data-updates-refresh="1">重新检查</button>
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

async function startUpgrade(targets) {
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

// ── Jupyter ────────────────────────────────────────────────────────────
async function loadJupyter() {
  const data = await api("/api/jupyter/kernels");
  state.kernels = data.kernels || [];
  const rows = state.kernels.map((kernel) => `<tr>
    <td><strong>${esc(kernel.name)}</strong>${kernel.default ? ` <span class="pill ok">默认</span>` : ""}</td>
    <td>${esc(kernel.display_name || "—")}</td>
    <td class="mono small">${esc(kernel.python || "—")}</td>
    <td>${kernel.managed ? `<span class="badge">启动器注册</span>` : ""}${kernel.broken ? ` <span class="badge missing">解释器不存在</span>` : ""}</td>
    <td class="actions"><button class="btn small" data-kact="use" data-kernel="${esc(kernel.name)}">设为默认</button>
      <button class="btn small ghost" data-kact="show" data-kernel="${esc(kernel.name)}">详情</button>
      <button class="btn small ghost" data-kact="rename" data-kernel="${esc(kernel.name)}">改名</button>
      <button class="btn small danger" data-kact="remove" data-kernel="${esc(kernel.name)}" data-managed="${kernel.managed ? "1" : ""}">删除</button></td>
  </tr>`).join("");
  shell(`${pageHead("Jupyter Lab", "内核注册与工作目录。修改默认内核会记住当前工作目录。",
    `<a class="btn ghost" href="#/jupyter/workdirs">工作目录</a><button class="btn ghost" data-refresh="jupyter">刷新</button>`)}
    <div class="card"><div class="spread"><h2>已安装内核</h2><span class="small muted">${state.kernels.length} 个</span></div>
      <div class="table-wrap"><table><thead><tr><th>内核</th><th>显示名</th><th>Python</th><th>状态</th><th></th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="muted">没有找到内核</td></tr>`}</tbody></table></div>
    </div>
    <div class="card" style="margin-top:16px"><h2>注册解释器</h2>
      <div class="form-grid">
        <label class="field"><span>项目目录（自动找 .venv）</span><div class="row"><input id="kernel-dir" placeholder="E:\\project" class="grow"><button class="btn small ghost" data-kernel-picker="dir">浏览</button></div></label>
        <label class="field"><span>或 Python 解释器</span><div class="row"><input id="kernel-python" class="grow"><button class="btn small ghost" data-kernel-picker="file">选择</button></div></label>
        <label class="field"><span>kernelspec id（可选）</span><input id="kernel-name"></label>
        <label class="field"><span>显示名（可选）</span><input id="kernel-display"></label>
        <div class="wide row"><label class="check"><input id="kernel-replace" type="checkbox"> 覆盖同名内核</label>
          <label class="check"><input id="kernel-install" type="checkbox"> 缺 ipykernel 时安装</label></div>
      </div>
      <div class="row" style="margin-top:12px"><button class="btn primary" data-kernel-add="1">注册内核</button></div>
    </div>`, "/jupyter");
}

async function loadWorkdirs() {
  const data = await api("/api/jupyter/workdirs");
  state.workdirs = data;
  const rows = (data.items || []).map((item) => `<tr>
    <td class="mono">${esc(item.path)}${item.current ? ` <span class="pill ok">当前</span>` : ""}</td>
    <td>${item.exists ? "存在" : `<span class="muted">不存在</span>`}</td>
    <td class="actions"><button class="btn small" data-workdir="${esc(item.path)}">切换到此目录</button></td>
  </tr>`).join("");
  shell(`${pageHead("Jupyter 工作目录", `当前：<span class="mono">${esc(data.current || "—")}</span>`,
    `<a class="btn ghost" href="#/jupyter">内核</a><button class="btn ghost" data-refresh="workdirs">刷新</button>`)}
    <div class="card"><div class="spread"><h2>最近目录</h2><span class="small muted">最多保留 10 个</span></div>
      <div class="table-wrap"><table><thead><tr><th>目录</th><th>状态</th><th></th></tr></thead><tbody>${rows || `<tr><td colspan="3" class="muted">还没有记录过工作目录</td></tr>`}</tbody></table></div>
    </div>
    <div class="card" style="margin-top:16px"><h2>选择目录</h2>
      <div class="form-row"><label class="field grow"><span>工作目录</span><div class="row"><input id="workdir-path" value="${esc(data.current || "")}" class="grow"><button class="btn small ghost" data-workdir-picker="dir">浏览</button></div></label>
        <label class="field"><span>默认内核（可选）</span><input id="workdir-kernel" placeholder="python3"></label><button class="btn primary" data-workdir-use="1">应用</button></div>
      <div class="small muted" style="margin-top:9px">切换后需要重启 Jupyter 才会改变服务端 root_dir；已有 notebook 不受影响。</div>
    </div>`, "/jupyter");
}

async function kernelAction(action, name, extra = {}) {
  if (action === "use") {
    await api(`/api/jupyter/kernels/${encodeURIComponent(name)}/use`, { method: "POST", body: {} });
    toast("默认内核已更新；重启 Jupyter 后生效", "ok");
  } else if (action === "show") {
    const data = await api(`/api/jupyter/kernels/${encodeURIComponent(name)}`);
    openModal("内核详情", `<pre class="logbox">${esc(JSON.stringify(data, null, 2))}</pre>`);
    return;
  } else if (action === "rename") {
    const display = prompt("新的显示名", name);
    if (!display) return;
    await api(`/api/jupyter/kernels/${encodeURIComponent(name)}`, { method: "PATCH", body: { display_name: display } });
    toast("显示名已更新", "ok");
  } else if (action === "remove") {
    let force = false;
    if (extra.managed) {
      if (!confirm(`删除内核 ${name}？`)) return;
    } else {
      if (!confirm("这不是启动器注册的内核。仍然删除？")) return;
      force = true;
    }
    await api(`/api/jupyter/kernels/${encodeURIComponent(name)}?force=${force ? "1" : "0"}`, { method: "DELETE", body: { force } });
    toast("内核已删除", "ok");
  }
  await loadJupyter();
}

// ── 诊断 / 关于 ────────────────────────────────────────────────────────
async function loadDoctor() {
  const data = await api("/api/doctor");
  state.doctor = data.rows || [];
  const rows = state.doctor.map((row) => `<tr><td>${esc(row.name)}</td><td class="mono">${esc(row.value)}</td></tr>`).join("");
  shell(`${pageHead("诊断", "依赖发现、平台后端、端口与运行时路径。",
    `<button class="btn ghost" data-refresh="doctor">重新检查</button><button class="btn" data-copy-doctor="1">复制 JSON</button>`)}
    <div class="card flush"><div class="table-wrap"><table><tbody>${rows || `<tr><td class="muted">没有诊断数据</td></tr>`}</tbody></table></div></div>`, "/doctor");
}

async function loadAbout() {
  const data = await api("/api/about");
  state.about = data;
  shell(`${pageHead("关于", "启动器版本、运行时路径和桌面入口。", "")}
    <div class="card"><div class="kv">
      <div class="k">版本</div><div class="v">${esc(data.version)}</div>
      <div class="k">平台</div><div class="v">${esc(data.platform)} · ${data.frozen ? "打包版" : "源码运行"}</div>
      <div class="k">数据目录</div><div class="v mono">${esc(data.data_dir)}</div>
      <div class="k">配置文件</div><div class="v mono">${esc(data.config)}</div>
      <div class="k">记忆文件</div><div class="v mono">${esc(data.memory)}</div>
      <div class="k">审计日志</div><div class="v mono">${esc(data.log)}</div>
      <div class="k">升级日志</div><div class="v mono">${esc(data.upgrades_log)}</div>
      <div class="k">Python</div><div class="v mono">${esc(data.python)}</div>
    </div></div>
    <div class="card" style="margin-top:16px"><h2>桌面入口</h2>
      <div class="small muted" style="margin-bottom:10px">创建主控制台入口，以及每个服务的快捷方式。</div>
      <div class="form-row">
        <label class="field"><span>图标路径（可选）</span><div class="row"><input id="install-icon" class="grow"><button class="btn small ghost" data-install-icon-picker="1">浏览</button></div></label>
        <label class="check"><input id="install-dsh" type="checkbox" checked> dsh 快捷方式</label>
        <label class="check"><input id="install-jupyter" type="checkbox" checked> Jupyter 快捷方式</label>
      </div>
      <div class="row" style="margin-top:12px"><button class="btn primary" data-install="1">安装桌面入口</button>
        <button class="btn" data-uninstall="1">删除启动器入口</button></div>
    </div>
    <div class="card" style="margin-top:16px"><h2>退出控制台</h2>
      <div class="small muted" style="margin-bottom:10px">关闭控制台会移除托盘图标。选择是否同时停止 dsh / Jupyter。</div>
      <div class="row"><button class="btn" data-quit="keep">退出（服务继续）</button>
        <button class="btn danger" data-quit="stop">退出并停止全部服务</button></div>
    </div>`, "/about");
}

// ── 弹窗 / 文件选择 ────────────────────────────────────────────────────
function openModal(title, html, onClose) {
  modalRoot.innerHTML = `<div class="modal-backdrop"><div class="modal">
    <div class="modal-head"><h2>${esc(title)}</h2><button class="btn small ghost" data-modal-close="1">关闭</button></div>
    <div id="modal-body">${html}</div></div></div>`;
  modalRoot._onClose = onClose || null;
}
function closeModal() {
  modalRoot.innerHTML = "";
  const callback = modalRoot._onClose;
  modalRoot._onClose = null;
  if (callback) callback();
}

async function openPicker(initial, includeFiles, onPick) {
  let current = initial || "";
  const render = async () => {
    let data;
    try { data = await api(`/api/fs?path=${encodeURIComponent(current)}&files=${includeFiles ? "1" : "0"}`); }
    catch (error) { toast(error.message, "err"); return; }
    current = data.path;
    const items = (data.entries || []).map((entry) => `<div class="dir-item ${entry.dir ? "dir" : ""}" data-pick-path="${esc(entry.path)}" data-pick-dir="${entry.dir ? "1" : "0"}">
      <span>${entry.dir ? "▸" : "·"} ${esc(entry.name)}</span><span class="tiny muted">${entry.dir ? "目录" : "文件"}</span></div>`).join("");
    openModal("选择路径", `<div class="row"><input id="picker-path" class="grow" value="${esc(current)}"><button class="btn small" data-pick-go="1">前往</button></div>
      <div class="dir-list">${items || `<div class="empty">没有可显示的目录</div>`}</div>
      <div class="row"><button class="btn ghost" data-pick-parent="${esc(data.parent || "")}" ${data.parent ? "" : "disabled"}>上一级</button>
      <button class="btn primary" data-pick-current="1">选择当前目录</button><button class="btn ghost" data-modal-close="1">取消</button></div>`, null);
    modalRoot.querySelector("[data-pick-go]").onclick = () => { current = q("picker-path").value; render(); };
    modalRoot.querySelectorAll("[data-pick-path]").forEach((node) => node.onclick = () => {
      if (node.dataset.pickDir === "1") { current = node.dataset.pickPath; render(); }
      else if (includeFiles) { closeModal(); onPick(node.dataset.pickPath); }
    });
    modalRoot.querySelector("[data-pick-parent]").onclick = () => { current = modalRoot.querySelector("[data-pick-parent]").dataset.pickParent; render(); };
    modalRoot.querySelector("[data-pick-current]").onclick = () => { closeModal(); onPick(current); };
  };
  await render();
}

// ── 动作 / 事件 ────────────────────────────────────────────────────────
async function runAction(action, services, force = false) {
  try {
    const job = await api("/api/actions", { method: "POST", body: { action, services, force } });
    toast(`${action} 已提交：${job.label}`, "ok");
    pollJob(job.id);
  } catch (error) { toast(error.message, "err"); }
}

async function pollJob(id) {
  for (let i = 0; i < 240; i += 1) {
    let job;
    try { job = await api(`/api/jobs/${encodeURIComponent(id)}`); } catch (error) { toast(error.message, "err"); return; }
    if (job.status === "succeeded") {
      toast(job.result ? String(job.result) : "操作完成", "ok");
      await refreshRoute();
      return;
    }
    if (job.status === "failed") {
      toast(job.error || "操作失败", "err");
      await refreshRoute();
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 650));
  }
}

async function refreshRoute() {
  try { await route(); } catch (error) { toast(error.message, "err"); }
}

async function route() {
  const rawPath = location.hash.slice(1) || "/";
  const [path, queryString = ""] = rawPath.split("?");
  const query = new URLSearchParams(queryString);
  if (path === "/updates") {
    if (query.get("profile")) sessionStorage.setItem("updates.profile", query.get("profile"));
    if (query.get("timeout")) sessionStorage.setItem("updates.timeout", query.get("timeout"));
  }
  state.route = path;
  if (path === "/" || path === "") return loadOverview();
  if (path === "/updates") return loadUpdates();
  if (path === "/jupyter") return loadJupyter();
  if (path === "/jupyter/workdirs") return loadWorkdirs();
  if (path === "/settings") return loadSettings();
  if (path === "/doctor") return loadDoctor();
  if (path === "/about") return loadAbout();
  if (path.startsWith("/services/")) return loadService(decodeURIComponent(path.split("/")[2] || ""));
  return loadOverview();
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-act], [data-refresh], [data-cfg-save], [data-cfg-unset], [data-cfg-raw], [data-picker], [data-kact], [data-kernel-add], [data-workdir], [data-workdir-use], [data-kernel-picker], [data-workdir-picker], [data-updates-refresh], [data-upgrade], [data-upgrade-all], [data-copy-doctor], [data-install], [data-install-icon-picker], [data-uninstall], [data-quit], [data-modal-close]");
  if (!target) return;
  try {
    if (target.dataset.modalClose) { closeModal(); return; }
    if (target.dataset.act) {
      const action = target.dataset.act;
      const services = target.dataset.service === "all" ? ["all"] : [target.dataset.service];
      if (action === "stop" && !target.dataset.force && !confirm("停止服务？正在使用的窗口会失去连接。")) return;
      await runAction(action, services, target.dataset.force === "1");
      return;
    }
    if (target.dataset.refresh === "overview") return loadOverview();
    if (target.dataset.refresh === "service") return loadService(target.dataset.service);
    if (target.dataset.refresh === "logs") return loadLogs(target.dataset.service);
    if (target.dataset.refresh === "settings") return loadSettings();
    if (target.dataset.refresh === "jupyter") return loadJupyter();
    if (target.dataset.refresh === "workdirs") return loadWorkdirs();
    if (target.dataset.refresh === "doctor") return loadDoctor();
    if (target.dataset.cfgSave) return saveConfigValue(target.dataset.cfgSave);
    if (target.dataset.cfgUnset) {
      if (!confirm(`删除配置项 ${target.dataset.cfgUnset}？`)) return;
      await api("/api/config/value", { method: "DELETE", body: { key: target.dataset.cfgUnset } });
      toast("配置项已删除", "ok"); return loadSettings();
    }
    if (target.dataset.cfgRaw) return saveRawConfig();
    if (target.dataset.picker) {
      const key = target.dataset.picker;
      const input = document.querySelector(`[data-cfg-input="${CSS.escape(key)}"]`);
      const files = /(node|bin|jupyter|icon)/.test(key);
      return openPicker(input?.value || "", files, (value) => { if (input) input.value = value; });
    }
    if (target.dataset.kact) return kernelAction(target.dataset.kact, target.dataset.kernel, { managed: !!target.dataset.managed });
    if (target.dataset.kernelAdd) {
      const payload = {
        dir: q("kernel-dir").value.trim() || undefined,
        python: q("kernel-python").value.trim() || undefined,
        name: q("kernel-name").value.trim() || undefined,
        display_name: q("kernel-display").value.trim() || undefined,
        replace: q("kernel-replace").checked,
        install_ipykernel: q("kernel-install").checked,
      };
      await api("/api/jupyter/kernels", { method: "POST", body: payload });
      toast("内核已注册", "ok"); return loadJupyter();
    }
    if (target.dataset.kernelPicker) {
      const input = q(target.dataset.kernelPicker === "dir" ? "kernel-dir" : "kernel-python");
      return openPicker(input.value || "", target.dataset.kernelPicker === "file", (value) => { input.value = value; });
    }
    if (target.dataset.workdir) {
      await api("/api/jupyter/workdirs", { method: "POST", body: { path: target.dataset.workdir } });
      toast("工作目录已切换；重启 Jupyter 后生效", "ok"); return loadWorkdirs();
    }
    if (target.dataset.workdirPicker) {
      const input = q("workdir-path");
      return openPicker(input.value || "", false, (value) => { input.value = value; });
    }
    if (target.dataset.workdirUse) {
      const body = { path: q("workdir-path").value.trim(), kernel: q("workdir-kernel").value.trim() || undefined };
      await api("/api/jupyter/workdirs", { method: "POST", body });
      toast("工作目录已保存；重启 Jupyter 后生效", "ok"); return loadWorkdirs();
    }
    if (target.dataset.updatesRefresh) {
      sessionStorage.setItem("updates.profile", q("updates-profile")?.value || "web");
      sessionStorage.setItem("updates.timeout", q("updates-timeout")?.value || "30");
      return loadUpdates(true);
    }
    if (target.dataset.upgradeAll) {
      const targets = state.updates ? buildTargets(state.updates) : [];
      return startUpgrade(targets);
    }
    if (target.dataset.upgrade) return startUpgrade([target.dataset.upgrade]);
    if (target.dataset.copyDoctor) {
      await navigator.clipboard.writeText(JSON.stringify(state.doctor, null, 2));
      toast("诊断 JSON 已复制", "ok"); return;
    }
    if (target.dataset.install) {
      const services = [];
      if (q("install-dsh").checked) services.push("dsh");
      if (q("install-jupyter").checked) services.push("jupyter");
      const result = await api("/api/install", { method: "POST", body: { services, icon: q("install-icon").value.trim() || undefined } });
      toast(`已创建 ${result.created.length} 个桌面入口`, "ok"); return;
    }
    if (target.dataset.installIconPicker) {
      const input = q("install-icon");
      return openPicker(input.value || "", true, (value) => { input.value = value; });
    }
    if (target.dataset.uninstall) {
      if (!confirm("删除启动器桌面入口？")) return;
      const result = await api("/api/uninstall", { method: "POST", body: {} });
      toast(`已删除 ${result.removed.length} 个入口`, "ok"); return;
    }
    if (target.dataset.quit) {
      const stop = target.dataset.quit === "stop";
      if (!confirm(stop ? "退出控制台并停止全部服务？" : "退出控制台？服务会继续运行。")) return;
      await api("/api/agent/quit", { method: "POST", body: { stop_services: stop } });
      document.body.innerHTML = `<div class="empty" style="padding-top:20vh"><h2>控制台已退出</h2><p>可以关闭此窗口。</p></div>`;
      return;
    }
  } catch (error) {
    toast(error.message || String(error), "err");
  }
});

function buildTargets(report) {
  const targets = [];
  if (report.dsh?.update_available && report.dsh?.upgrade_supported) targets.push("dsh");
  for (const plugin of report.profile?.plugins || []) if (plugin.update_available) targets.push("plugin:" + plugin.name);
  return targets;
}

// ── 启动 / 刷新 ────────────────────────────────────────────────────────
async function boot() {
  try {
    state.meta = await api("/api/meta");
    await route();
    window.addEventListener("hashchange", () => route().catch((error) => { shell(errorCard(error), location.hash); }));
    setInterval(() => {
      if (document.visibilityState !== "visible" || modalRoot.innerHTML) return;
      if (state.route === "/") loadOverview().catch(() => {});
    }, 2500);
  } catch (error) {
    app.innerHTML = `<div class="empty" style="grid-column:1/-1"><h2>无法连接控制台</h2><p>${esc(error.message)}</p>
      <p>请从启动器重新打开，或执行 <code>weblauncher ui</code>。</p></div>`;
  }
}

boot();
