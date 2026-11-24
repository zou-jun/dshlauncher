import {
  state, app, modalRoot, esc, q, toast, api, shell, errorCard, closeModal, openPicker,
} from "./core.js";
import { loadOverview } from "./pages/overview.js";
import { loadService } from "./pages/service.js";
import { loadLogs, loadLogPage, stopLogTimer } from "./pages/logs.js";
import { loadSettings, saveConfigValue, saveRawConfig } from "./pages/settings.js";
import { loadUpdates, startUpgrade, buildTargets } from "./pages/updates.js";
import { loadJupyter, loadWorkdirs, kernelAction } from "./pages/jupyter.js";
import { loadDoctor } from "./pages/doctor.js";
import { loadAbout } from "./pages/about.js";

// ── 动作 / 路由 / 事件 ────────────────────────────────────────────────
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
  stopLogTimer();
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
  if (path.startsWith("/settings/")) return loadSettings(decodeURIComponent(path.split("/")[2] || ""));
  if (path === "/doctor") return loadDoctor();
  if (path === "/about") return loadAbout();
  if (path.startsWith("/logs/")) return loadLogPage(decodeURIComponent(path.split("/")[2] || ""));
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
    if (target.dataset.refresh === "logs") return loadLogs(target.dataset.service || state.logService).catch((error) => toast(error.message, "err"));
    if (target.dataset.refresh === "settings") return loadSettings(state.configScope);
    if (target.dataset.refresh === "jupyter") return loadJupyter();
    if (target.dataset.refresh === "workdirs") return loadWorkdirs();
    if (target.dataset.refresh === "doctor") return loadDoctor();
    if (target.dataset.cfgSave) return saveConfigValue(target.dataset.cfgSave);
    if (target.dataset.cfgUnset) {
      if (!confirm(`删除配置项 ${target.dataset.cfgUnset}？`)) return;
      await api("/api/config/value", { method: "DELETE", body: { key: target.dataset.cfgUnset } });
      toast("配置项已删除", "ok"); return loadSettings(state.configScope);
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

document.addEventListener("change", (event) => {
  const target = event.target;
  if (target.matches("[data-log-auto]")) {
    state.logAuto = target.checked;
    startLogTimer();
    return;
  }
  if (target.matches("[data-log-tail]")) {
    state.logTail = Number(target.value) || 300;
    loadLogs(state.logService).catch((error) => toast(error.message, "err"));
  }
});

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
