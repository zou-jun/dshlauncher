import {
  api, state, esc, shell, pageHead, empty, breadcrumb, serviceTabs, servicePath,
} from "../core.js";
import { configField } from "./settings.js";

export async function loadServiceSettings(id) {
  const target = servicePath(id, "settings");
  const [data, service] = await Promise.all([
    api("/api/config"),
    api(`/api/services/${encodeURIComponent(id)}`),
  ]);
  if (state.route !== target) return;
  state.config = data;
  state.configScope = id;
  state.service = service;
  const fields = (data.fields || [])
    .filter((field) => String(field.key || "").split(".")[0] === id)
    .map((field) => configField(field, data.values?.[field.key]))
    .join("");
  const crumbs = breadcrumb([
    { label: "总览", path: "/" },
    { label: service.label, path: servicePath(id) },
    { label: "设置" },
  ]);
  shell(`${crumbs}${pageHead(`${service.label} 设置`, `只显示 <span class="mono">[${esc(id)}]</span> 段；保存后运行中的服务需要重启。`,
    `<button class="btn ghost" data-refresh="service-settings" data-service="${esc(id)}">重新读取</button>`)}
    ${serviceTabs(service, "settings")}
    <div class="card">
      <div class="small muted" style="margin-bottom:14px">配置文件：<span class="mono">${esc(data.path)}</span></div>
      <div class="form-grid">${fields || empty("这个服务没有可编辑的配置项")}</div>
    </div>`, target);
}
