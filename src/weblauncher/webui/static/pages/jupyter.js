import { api, state, esc, toast, shell, pageHead, openModal } from "../core.js";

export async function loadJupyter() {
  const data = await api("/api/jupyter/kernels");
  if (state.route !== "/jupyter") return;
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
  shell(`${pageHead("Jupyter 配置", "内核注册与工作目录。修改默认内核会记住当前工作目录。",
    `<a class="btn ghost" href="#/">返回总览</a>
     <a class="btn ghost" href="#/settings/jupyter">Jupyter 设置</a>
     <a class="btn ghost" href="#/jupyter/workdirs">工作目录</a><button class="btn ghost" data-refresh="jupyter">刷新</button>`)}
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

export async function loadWorkdirs() {
  const data = await api("/api/jupyter/workdirs");
  if (state.route !== "/jupyter/workdirs") return;
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

export async function kernelAction(action, name, extra = {}) {
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
