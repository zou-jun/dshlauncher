import { esc } from "../core.js";

export function statusClass(value) {
  return value === "running" ? "ok" : value === "stopped" ? "" : value === "error" ? "err" : "warn";
}

export function statusText(service) {
  if (service.error) return "不可用";
  if (service.busy) return "操作中";
  return service.running ? "运行中" : "已停止";
}

export function pill(service) {
  return `<span class="pill ${statusClass(service.error ? "error" : service.busy ? "" : service.running ? "running" : "stopped")}">
    <span class="dot ${service.running ? "ok" : service.error ? "err" : ""}"></span>${esc(statusText(service))}</span>`;
}
