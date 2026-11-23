# Changelog

## 0.4.0

- 新增 `updates`：检查 dsh 全局安装与 `web` profile 插件的更新，支持 `--json` 与退出码。
- 新增本地更新面板：托盘「检查更新…」或 `updates --panel` 打开，可逐项/全部升级。
- 升级流程自动停服与重启：先 dsh，再插件；使用 npm/pnpm 与 `dsh plugin add --save-exact`。
- 面板使用独立 `panel-browser/` Chromium 配置，loopback + 随机 token + Host 校验。
- 更新检查复用 npm/pnpm registry 配置，不另存凭据；非 registry 依赖标记为跳过。

## 0.3.0

- 双击进入系统托盘：打开 dsh 窗口后常驻，右键菜单承载打开/停止/重启/刷新/日志/数据目录/退出。
- 服务未就绪时先打开本地启动过场页，就绪后自动跳转；托盘状态/ tooltip 显示「启动中」。
- 托盘单实例：`tray.lock` + loopback IPC，重复双击只打开/置前窗口。
- 「服务状态」菜单项点击弹出原生详情框（Windows MessageBoxW、Linux zenity/kdialog、macOS osascript）。
- 「退出并停止服务」按约定停止 dsh；窗口保留。
- 删除 tkinter 控制面板与 `ui` 命令；错误提示统一走平台后端。
- `state.json` 改为原子写；`stop` 只处理可信实例/目标端口，端口未释放时保留状态文件。
- `launcher.log` 按 1 MB 轮转，异常记录附带调用点摘要。
- Chrome 启动在受限 Job 下 `CREATE_BREAKAWAY_FROM_JOB` 失败时回退普通分离。
- Windows `netsh` 端口保留段探测使用 `CREATE_NO_WINDOW`，GUI 启动不再闪终端窗口。
- Windows 桌面入口只保留 `dsh.lnk`；Linux 只保留 `dsh.desktop`。
- 依赖加入 `pystray` / `Pillow`；PyInstaller 按平台裁剪托盘后端。

## 0.2.0

- 端口自动回退、Linux 支持、tkinter 控制面板、桌面入口与 PyInstaller 打包。
