import {
  api, state, esc, toast, shell, pageHead, empty, breadcrumb,
} from "../core.js";

export async function loadLauncherSettings() {
  const target = "/settings";
  const data = await api("/api/config");
  if (state.route !== target) return;
  state.config = data;
  state.configScope = "general";
  const fields = (data.fields || [])
    .filter((field) => {
      const section = String(field.key || "").split(".")[0];
      return section !== "dsh" && section !== "jupyter";
    })
    .map((field) => configField(field, data.values?.[field.key]))
    .join("");
  const crumbs = breadcrumb([{ label: "总览", path: "/" }, { label: "启动器设置" }]);
  shell(`${crumbs}${pageHead("启动器设置", `启动器、控制台和浏览器配置。配置文件：<span class="mono">${esc(data.path)}</span>`,
    `<a class="btn ghost" href="#/settings/advanced">高级 TOML</a>
     <button class="btn ghost" data-refresh="settings">重新读取</button>`)}
    <div class="card">
      <div class="small muted" style="margin-bottom:14px">优先级：命令行 / 环境变量 &gt; <code>config.toml</code> &gt; 默认值。保存后运行中的服务需要重启。</div>
      <div class="form-grid">${fields || empty("这一组没有可编辑的配置项")}</div>
    </div>`, target);
}

export async function loadAdvancedSettings() {
  const target = "/settings/advanced";
  const data = await api("/api/config");
  if (state.route !== target) return;
  state.config = data;
  state.configScope = "advanced";
  const crumbs = breadcrumb([
    { label: "总览", path: "/" },
    { label: "启动器设置", path: "/settings" },
    { label: "高级 TOML" },
  ]);
  shell(`${crumbs}${pageHead("高级 TOML", "直接编辑完整 config.toml；保存前会做 TOML 校验，注释会原样保留。",
    `<button class="btn ghost" data-refresh="advanced">重新读取</button>`)}
    <div class="card">
      <textarea id="raw-config" spellcheck="false">${esc(data.raw)}</textarea>
      <div class="row" style="margin-top:10px"><button class="btn primary" data-cfg-raw="1">保存 TOML</button>
        <button class="btn ghost" data-refresh="advanced">放弃修改</button></div>
    </div>`, target);
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
  if (state.route === "/settings/advanced") await loadAdvancedSettings();
}
