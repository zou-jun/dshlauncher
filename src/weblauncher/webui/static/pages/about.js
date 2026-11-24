import { api, state, esc, shell, pageHead } from "../core.js";

export async function loadAbout() {
  const data = await api("/api/about");
  if (state.route !== "/about") return;
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
