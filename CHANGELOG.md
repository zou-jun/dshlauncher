# Changelog

## 0.7.1

- Windows 托管进程改用 `CREATE_NO_WINDOW` 分离标志，修复通过 `jupyter-lab.exe` 启动 Jupyter 时额外出现的终端窗口；Jupyter 日志仍写入 `service.log`。
- 进程树仍通过 `CREATE_NEW_PROCESS_GROUP` + `CREATE_BREAKAWAY_FROM_JOB` 与启动器分离，关闭终端/控制台不影响服务。

## 0.7.0

- 启动器改为「常驻 Agent + Web 控制台」：服务启停、状态、日志、配置、诊断、Jupyter 内核/工作目录、更新、安装与退出统一在 `http://127.0.0.1` 控制台。
- 默认双击/无参数启动改为打开控制台；托盘只保留打开控制台和退出入口，删除旧的多级服务菜单与原生状态弹窗。
- 控制台使用一次性 bootstrap ticket + HttpOnly Cookie + CSRF/Host/Origin 校验；服务 token 不返回页面，URL 只显示脱敏值。
- 独立更新面板与启动过场页并入控制台；删除 `panel.py`、`splash.py` 与 `panel-browser/` 使用路径。
- 桌面快捷方式改为 `ui` / `ui <service>`；更新日志、状态和配置操作增加结构化 API。
- 新增控制台后端/认证/任务与 Web 资源测试。

## 0.6.1

- 修复 Jupyter `--port 0`：就绪只读取本次启动标记、ownership 接受 argv 中的 `0`，`status/stop/restart` 不再丢失动态端口实例。
- start/stop/restart 增加跨进程服务锁；托盘空参数 open 也走服务动作锁，避免并发启动产生孤儿进程。
- 浏览器打开改为一次性 ticket 跳转，服务/面板 token 不再进入 Chromium argv；运行日志、配置和目录收紧权限并脱敏审计。
- 修复 Jupyter 的 `WEBLAUNCHER_JUPYTER_BIN`、内核目录优先级、首次按目录内核记忆、代理绕过、IPv6/括号路径与优雅停止存活检查。
- 修复托盘 open 超时、退出时并发停止、查看日志目录、面板 `localhost` Origin、配置 `list`、动态端口状态展示、Linux 桌面入口旧文件清理与版本排序。

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
