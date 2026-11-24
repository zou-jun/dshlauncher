# Changelog

## 0.10.0

- 控制台改为服务优先的信息架构：左侧栏按「服务 / 配置 / 其他」分组，诊断/设置归入配置区并用图标颜色区分；服务日志、诊断、设置和专属工具都在 `#/services/<id>/` 子树。
- 服务详情成为子树根，统一提供日志、诊断、设置和服务工具标签；Jupyter 内核/工作目录、dsh 更新不再挂在总览卡片。
- 设置拆成启动器设置（`#/settings`、`#/settings/advanced`）和服务设置（`#/services/<id>/settings`）；诊断拆成启动器诊断（`#/diagnostics`）和服务诊断（`#/services/<id>/diagnostics`）。
- `ServiceSpec.console_tools` 改为相对 slug；后端不再保存 `/api/services/...` 绝对链接，前端用 `servicePath()` 生成路径和面包屑。
- 单窗口模式新增 `ui.single_window_profile`：`tabbed` 使用独立 `tabbed-browser`，`daily` 直接使用日常 Chrome 默认配置（共享书签、登录和扩展）；`doctor` 显示当前浏览器配置。
- 旧地址 `#/logs/<id>`、`#/settings/<id>`、`#/jupyter`、`#/updates`、`#/doctor` 保留 query 并重定向；`smoke_ui.py` 覆盖新路径和旧地址重定向。
- 路径选择器支持「起始位置」回到盘符/主目录；Jupyter 工作目录浏览从盘符开始，初始路径失效时自动回退到起始位置。

## 0.9.0

- 控制台 HTTP 改为 `control/routes.py` 表驱动；GET/POST/PUT/PATCH/DELETE 统一按方法 + 路径模式分发。
- 新增 `inspector.PortInspector`：一次 `net_connections` 扫描缓存全部监听端口，`Supervisor` 的占用者/进程判定在短 TTL 内复用。
- 前端总览、服务详情、日志拆成 `pages/overview.js`、`pages/service.js`、`pages/logs.js` 与共享 `pages/status.js`；`app.js` 只保留动作、路由、事件和启动约 200 行。
- 新增 `scripts/smoke_ui.py`：headless Chromium + CDP 实际执行总览、设置、服务、日志、诊断异步 Job，并检查全部静态 ES modules；支持 `--exe` 测试打包版。`make smoke-ui` 运行。
- 诊断与更新检查的后台 Job、静态资源路径保护保持。
- 修复 Jupyter 默认 profile 被公共配置覆盖为 dsh 全局 profile 的回归；Jupyter 继续使用 `services/jupyter/browser/`。
- Jupyter 只切换工作目录时不再要求先定位 Jupyter Lab 安装。

## 0.8.5

- `control/server.py` 拆出 `jobs.py` 与 `static_assets.py`；后台任务和静态资源路径校验独立维护。
- 诊断与 dsh 更新检查改为 `JobManager` 后台任务：新增 `POST /api/doctor`、`POST /api/updates`，页面先显示检查中，完成后再渲染。
- 前端新增 `waitForJob()`；设置/诊断/更新/Jupyter 页面模块保持不变。

## 0.8.4

- 前端拆成 `core.js` + `pages/*.js` ES modules：总览/服务/日志保留入口层，设置、更新、Jupyter、诊断、关于独立；`app.js` 从约 820 行降到约 390 行。
- 控制台静态路由支持 `/core.js` 与 `/pages/*.js`，并限制解析后的路径必须位于 `webui/static/` 内。

## 0.8.3

- 抽取 `services/common_settings.py`：dsh / Jupyter 共用 host、port、browser、ozone、profile、窗口和超时解析，数据类改为共享基类。
- `control/backend.py` 拆成门面 + `config_store` / `files` / `jupyter` / `updates` 领域模块；服务动作、配置、文件浏览、Jupyter 与升级任务职责分离。

## 0.8.2

- 将服务动作控制器从 `tray/` 移到 `controller.py`，控制台不再反向依赖托盘；控制器集合改为线程安全的快照注册表。
- 删除 `ServiceDefinition`，`open_on_start` 等服务元数据统一放在 `ServiceSpec`。
- 抽取 `services/jupyter/operations.py`，CLI 与控制台共用 Python 解析、内核注册/选择/删除和工作目录切换逻辑；删除两份 `_python_from_dir` 和重复的服务诊断代码。
- 配置重载整体替换控制器快照，构建失败的服务保留为概要页错误占位，不再从总览静默消失。

## 0.8.1

- 控制台重新分组：左侧栏只保留总览 / 诊断 / 设置 / 关于；dsh 更新与设置、Jupyter 配置与设置作为总览服务卡片入口。
- 日志改为 Web 日志页：支持行数切换与自动刷新，不再调用外部编辑器打开 `service.log`。
- 诊断拆分为启动器通用环境与各服务独立卡片；设置拆分为控制台设置与各服务设置。
- 托盘默认菜单项改为「打开控制台」，双击（或单击）图标直接打开；带 0.6 秒防抖避免双击打开两次。
- Agent/控制台启动不再自动启动 dsh 或其他服务，服务必须由用户在控制台显式启动。

## 0.8.0

- 新增 `[ui] single_window`（环境变量 `WEBLAUNCHER_SINGLE_WINDOW`）：控制台与所有服务共用一个普通 Chromium 窗口，每个页面一个标签页；首次打开建窗口，后续只追加标签页。
- 单窗口模式使用共用的 `tabbed-browser/` profile，不再使用每个服务的 `--app` 窗口；控制台的设置页可直接切换，修改后重启 Agent 生效。

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
