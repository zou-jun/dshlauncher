import { state, esc, q, toast, api, shell, pageHead } from "../core.js";

export async function loadLogs(id, tail = state.logTail || 300) {
  try {
    const data = await api(`/api/services/${encodeURIComponent(id)}/logs?tail=${encodeURIComponent(tail)}`);
    if (state.logService !== id) return;
    state.logText = data.text;
    const box = q("logbox");
    if (box) {
      const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
      box.textContent = data.text || "（日志为空）";
      if (atBottom) box.scrollTop = box.scrollHeight;
    }
    const path = q("logpath");
    if (path) path.textContent = data.path;
    const meta = q("logmeta");
    if (meta) meta.textContent = `${data.lines || 0} 行 · ${data.path}`;
  } catch (error) {
    if (state.route === `/logs/${id}`) throw error;
    toast(error.message, "err");
  }
}

export function stopLogTimer() {
  if (state.logTimer) {
    clearInterval(state.logTimer);
    state.logTimer = null;
  }
}

export function startLogTimer() {
  stopLogTimer();
  if (!state.logAuto) return;
  state.logTimer = setInterval(() => {
    if (document.visibilityState !== "visible" || !q("logbox") || !state.logService) return;
    loadLogs(state.logService).catch(() => {});
  }, 2000);
}

export async function loadLogPage(id) {
  const service = await api(`/api/services/${encodeURIComponent(id)}`);
  if (state.route !== `/logs/${id}`) return;
  state.service = service;
  state.logService = id;
  renderLogPage(service);
  await loadLogs(id);
  startLogTimer();
}

function renderLogPage(service) {
  const id = service.id;
  const tailOptions = [100, 300, 1000, 2000].map((value) =>
    `<option value="${value}" ${value === state.logTail ? "selected" : ""}>${value} 行</option>`).join("");
  shell(`${pageHead(`${service.label} 日志`, "日志只在本页读取和显示，不打开外部编辑器。",
    `<a class="btn ghost" href="#/services/${encodeURIComponent(id)}">服务详情</a>
     <a class="btn ghost" href="#/">返回总览</a>
     <button class="btn ghost" data-refresh="logs" data-service="${esc(id)}">刷新</button>`)}
    <div class="card">
      <div class="spread"><h2>日志尾部</h2><span class="small muted" id="logmeta">${esc(service.log || "")}</span></div>
      <div class="row log-tools">
        <label class="field"><span>显示行数</span><select id="log-tail" data-log-tail="1">${tailOptions}</select></label>
        <label class="check"><input type="checkbox" id="log-auto" data-log-auto="1" ${state.logAuto ? "checked" : ""}> 自动刷新（2 秒）</label>
      </div>
      <pre class="logbox" id="logbox">${esc(state.logText || "正在读取…")}</pre>
    </div>`, `/logs/${id}`);
}
