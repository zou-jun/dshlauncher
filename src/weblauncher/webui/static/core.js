export const state = {
  meta: null,
  services: [],
  jobs: [],
  route: "/",
  service: null,
  logText: "",
  logService: null,
  logTail: 300,
  logAuto: true,
  logTimer: null,
  config: null,
  configScope: "general",
  kernels: [],
  workdirs: null,
  updates: null,
  upgradeJob: null,
  about: null,
  doctor: null,
};

export const app = document.getElementById("app");
export const toasts = document.getElementById("toasts");
export const modalRoot = document.getElementById("modal-root");

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

export function q(id) { return document.getElementById(id); }

export function toast(message, kind = "") {
  const node = document.createElement("div");
  node.className = "toast " + kind;
  node.textContent = message;
  toasts.append(node);
  setTimeout(() => node.remove(), 5200);
}

export function serviceIcon(service, className = "service-icon") {
  if (!service?.icon) return "";
  return `<img class="${className}" src="/icons/${encodeURIComponent(service.icon)}.png" alt="">`;
}

export function activeNav(path) {
  if (path.startsWith("/services/")) return "/";
  if (path === "/diagnostics") return "/diagnostics";
  if (path === "/settings" || path.startsWith("/settings/")) return "/settings";
  return path;
}

export function servicePath(id, child = "") {
  const base = `/services/${encodeURIComponent(id)}`;
  return child ? `${base}/${encodeURIComponent(child)}` : base;
}

export function breadcrumb(items) {
  const parts = items.map((item, index) => {
    const current = index === items.length - 1;
    const text = esc(item.label);
    return current || !item.path
      ? `<span aria-current="page">${text}</span>`
      : `<a href="#${esc(item.path)}">${text}</a>`;
  });
  return `<nav class="breadcrumb" aria-label="面包屑">${parts.join('<span class="crumb-sep">/</span>')}</nav>`;
}

export function serviceTabs(service, active = "") {
  const tabs = [
    { slug: "", label: "概览" },
    { slug: "logs", label: "日志" },
    { slug: "diagnostics", label: "诊断" },
    { slug: "settings", label: "设置" },
    ...(service.tools || []).map((tool) => ({ slug: tool.slug, label: tool.label })),
  ];
  const seen = new Set();
  return `<nav class="section-tabs" aria-label="${esc(service.label)} 子页面">${tabs
    .filter((tab) => {
      const key = tab.slug;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map((tab) => {
      const href = `#${servicePath(service.id, tab.slug)}`;
      const cls = tab.slug === active ? "active" : "";
      return `<a class="${cls}" href="${href}">${esc(tab.label)}</a>`;
    })
    .join("")}</nav>`;
}

export async function api(path, options = {}) {
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

export function shell(main, path) {
  const navGroups = [
    { label: "服务", items: [["/", "▦", "总览", "overview"]] },
    { label: "配置", items: [["/diagnostics", "✚", "诊断", "inspect"], ["/settings", "⚙", "设置", "config"]] },
    { label: "其他", items: [["/about", "ⓘ", "关于", "info"]] },
  ];
  const links = navGroups.map((group) => `<div class="nav-label">${group.label}</div>${group.items.map(([href, icon, label, tone]) => {
    const cls = activeNav(path) === href ? "active" : "";
    return `<a class="${cls}" data-tone="${tone}" href="#${href}"><span class="nav-icon">${icon}</span>${label}</a>`;
  }).join("")}`).join("");
  app.innerHTML = `<aside class="sidebar">
    <div class="brand"><img class="brand-mark" src="/icons/control.png" alt=""><div>
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

export function pageHead(title, sub, actions = "", icon = "") {
  return `<div class="page-head"><div><div class="page-title">${icon}<h1>${esc(title)}</h1></div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>
    <div class="toolbar">${actions}</div></div>`;
}

export function errorCard(error) {
  return `<div class="card notice"><strong>加载失败</strong><div class="small" style="margin-top:6px">${esc(error.message || error)}</div></div>`;
}

export function empty(text) { return `<div class="empty">${esc(text)}</div>`; }

export function openModal(title, html, onClose) {
  modalRoot.innerHTML = `<div class="modal-backdrop"><div class="modal">
    <div class="modal-head"><h2>${esc(title)}</h2><button class="btn small ghost" data-modal-close="1">关闭</button></div>
    <div id="modal-body">${html}</div></div></div>`;
  modalRoot._onClose = onClose || null;
}

export function closeModal() {
  modalRoot.innerHTML = "";
  const callback = modalRoot._onClose;
  modalRoot._onClose = null;
  if (callback) callback();
}

export async function openPicker(initial, includeFiles, onPick) {
  let current = initial || "";
  let fallbackAvailable = Boolean(current);
  const render = async () => {
    let data;
    try { data = await api(`/api/fs?path=${encodeURIComponent(current)}&files=${includeFiles ? "1" : "0"}`); }
    catch (error) {
      if (fallbackAvailable) {
        fallbackAvailable = false;
        current = "";
        toast(`${error.message}；已从起始位置重新开始`, "warn");
        return render();
      }
      toast(error.message, "err");
      return;
    }
    fallbackAvailable = false;
    current = data.path;
    const items = (data.entries || []).map((entry) => `<div class="dir-item ${entry.dir ? "dir" : ""}" data-pick-path="${esc(entry.path)}" data-pick-dir="${entry.dir ? "1" : "0"}">
      <span>${entry.dir ? "▸" : "·"} ${esc(entry.name)}</span><span class="tiny muted">${entry.dir ? "目录" : "文件"}</span></div>`).join("");
    openModal("选择路径", `<div class="row"><input id="picker-path" class="grow" placeholder="输入路径，或从下方选择盘符/目录" value="${esc(current)}"><button class="btn small" data-pick-go="1">前往</button></div>
      <div class="dir-list">${items || `<div class="empty">没有可显示的目录</div>`}</div>
      <div class="row"><button class="btn ghost" data-pick-roots="1" ${data.path ? "" : "disabled"}>起始位置</button>
      <button class="btn ghost" data-pick-parent="${esc(data.parent || "")}" ${data.parent ? "" : "disabled"}>上一级</button>
      <button class="btn primary" data-pick-current="1" ${data.path ? "" : "disabled"}>选择当前目录</button><button class="btn ghost" data-modal-close="1">取消</button></div>`, null);
    modalRoot.querySelector("[data-pick-go]").onclick = () => { current = q("picker-path").value; render(); };
    modalRoot.querySelector("[data-pick-roots]").onclick = () => { current = ""; render(); };
    modalRoot.querySelectorAll("[data-pick-path]").forEach((node) => node.onclick = () => {
      if (node.dataset.pickDir === "1") { current = node.dataset.pickPath; render(); }
      else if (includeFiles) { closeModal(); onPick(node.dataset.pickPath); }
    });
    modalRoot.querySelector("[data-pick-parent]").onclick = () => { current = modalRoot.querySelector("[data-pick-parent]").dataset.pickParent; render(); };
    modalRoot.querySelector("[data-pick-current]").onclick = () => { closeModal(); onPick(current); };
  };
  await render();
}

export async function waitForJob(id, { attempts = 600, interval = 500 } = {}) {
  for (let i = 0; i < attempts; i += 1) {
    const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
    if (job.status === "succeeded" || job.status === "failed") return job;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
  throw new Error("任务执行超时");
}
