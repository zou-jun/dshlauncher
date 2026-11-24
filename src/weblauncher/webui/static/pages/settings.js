import { api, state, esc, toast, shell, pageHead, empty } from "../core.js";

export async function loadSettings(scope = "general") {
  const target = scope === "general" ? "/settings" : `/settings/${scope}`;
  const [data, service] = await Promise.all([
    api("/api/config"),
    scope === "general" ? null : api(`/api/services/${encodeURIComponent(scope)}`),
  ]);
  if (state.route !== target) return;
  state.config = data;
  state.configScope = scope;
  const fields = (data.fields || []).filter((field) => {
    const key = String(field.key || "");
    const section = key.split(".")[0];
    return scope === "general" ? section !== "dsh" && section !== "jupyter" : section === scope;
  }).map((field) => configField(field, data.values?.[field.key])).join("");
  const label = service?.label || scope;
  const title = scope === "general" ? "控制台设置" : `${label} 设置`;
  const sub = scope === "general"
    ? `启动器、控制台和浏览器配置；具体服务配置在各自服务页。配置文件：<span class="mono">${esc(data.path)}</span>`
    : `只显示 <span class="mono">[${esc(scope)}]</span> 段；控制台通用配置见 <a href="#/settings" style="color:var(--accent)">控制台设置</a>。`;
  const raw = scope === "general"
    ? `<div class="card" style="margin-top:16px"><h2>高级 TOML</h2>
        <div class="small muted" style="margin-bottom:10px">直接编辑原文件（包含各服务段），保存前会做 TOML 校验；注释会原样保留。</div>
        <textarea id="raw-config" spellcheck="false">${esc(data.raw)}</textarea>
        <div class="row" style="margin-top:10px"><button class="btn primary" data-cfg-raw="1">保存 TOML</button>
          <button class="btn ghost" data-refresh="settings">放弃修改</button></div>
      </div>`
    : `<div class="card" style="margin-top:16px"><h2>高级 TOML</h2>
        <div class="small muted">服务段也可以直接在 <a href="#/settings" style="color:var(--accent)">控制台设置</a> 的高级 TOML 里编辑。</div>
      </div>`;
  shell(`${pageHead(title, sub,
    `${scope === "general" ? "" : `<a class="btn ghost" href="#/settings">控制台设置</a>`}
     <button class="btn ghost" data-refresh="settings">重新读取</button>`)}
    <div class="card"><h2>${scope === "general" ? "控制台" : esc(label)}</h2>
      <div class="small muted" style="margin-bottom:14px">优先级：命令行 / 环境变量 &gt; <code>config.toml</code> &gt; 默认值。保存后运行中的服务需要重启。</div>
      <div class="form-grid">${fields || empty("这一组没有可编辑的配置项")}</div>
    </div>${raw}`, target);
}

export function configField(field, value) {
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

export async function saveConfigValue(key) {
  const input = document.querySelector(`[data-cfg-input="${CSS.escape(key)}"]`);
  if (!input) return;
  let value;
  if (input.type === "checkbox") value = input.checked;
  else if (input.type === "number") value = Number(input.value);
  else value = input.value;
  await api("/api/config/value", { method: "PUT", body: { key, value } });
  toast(`${key} 已保存；运行中的服务需重启`, "ok");
}

export async function saveRawConfig() {
  const raw = document.getElementById("raw-config").value;
  await api("/api/config", { method: "PUT", body: { raw } });
  toast("配置已保存；运行中的服务需重启", "ok");
  await loadSettings(state.configScope);
}
