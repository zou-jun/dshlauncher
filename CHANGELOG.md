# Changelog

## 0.6.0

- 项目更名为 `weblauncher`：包名、exe、console script、数据目录、PyInstaller spec 与文档统一。
- 数据目录 `.dshlauncher/` 首次启动时自动改名为 `.weblauncher/`；旧的单服务文件仍继续迁移到 `services/dsh/`。
- 环境变量改为统一前缀：`WEBLAUNCHER_*`（共享）、`WEBLAUNCHER_DSH_*`、`WEBLAUNCHER_JUPYTER_*`。
- 桌面入口主快捷方式改为 `weblauncher.lnk` / `weblauncher.desktop`，并清理旧 `dsh.lnk` / `dshlauncher.*`。
- 托盘标题改为「Web 服务启动器」。

## 0.5.0

- 架构拆分为共享核心 + 服务适配器：`Supervisor` 只负责端口/进程/就绪/状态，dsh 与 Jupyter 各自实现 `ServiceAdapter`。
- 新增 Jupyter Lab 托管：uv tool 发现、随机 token、`/api/status` 就绪、`POST /api/shutdown` 优雅停止。
- 新增 `jupyter kernel add/list/show/use/rename/remove`：注册任意 venv 解释器、改显示名、设默认内核。
- 新增 `jupyter workdir use/list/current`：工作目录持久化、最近目录、按目录记忆内核。
- 新增 `config list/get/set/unset/path`：按行编辑 `config.toml`，保留手写注释。
- 数据布局改为 `services/<id>/state.json|service.log|browser/`，旧单服务文件自动迁移。
- CLI 改为 `start|stop|restart|open <dsh|jupyter|all>`；`status` / `doctor` 支持多服务与 `--json`。
- 托盘按服务分组，支持启动/停止全部；每服务独立动作锁，批量操作固定顺序加锁。
- 跨服务端口排除；Jupyter 不接管手动实例，dsh 保留接管同类实例的行为。
- 桌面入口新增每个服务的快捷方式；`dsh updates` 保留旧 `updates` 别名。
- 版本升至 0.5.0。

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
