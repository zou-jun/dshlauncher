# weblauncher

一个启动器托管多个本地服务：**dsh web** 与 **Jupyter Lab**。每个服务都是独立的分离进程，拥有独立的状态、日志与 Chromium 配置。

- 服务以分离进程运行：关掉终端、关掉窗口都不影响它；只有托盘的「退出并停止全部服务」会显式停掉
- 双击进入系统托盘：菜单按服务分组，可单独启动/打开/停止/重启、看日志
- dsh 启动慢时先开本地过场页；Jupyter 启动前自动选空闲端口并生成 token
- Jupyter 的工作目录、默认内核按目录记忆；内核可直接注册任意 uv 项目 venv
- 新服务 = `services/<id>/` 适配器 + 注册表一行，核心/托盘/CLI 不改
- Windows 完整支持；Linux 完整支持（X11 / XWayland，见「平台差异」）；macOS 尽力而为

## 安装

### Windows 打包版

解压后的目录里有：

只有一个 `weblauncher.exe`（GUI 子系统），按有没有参数切换形态：

| 启动方式 | 行为 |
|---|---|
| 双击 exe / 桌面快捷方式 | 等同 `tray`：确保服务在跑、打开窗口，并常驻系统托盘 |
| 终端里带参数 | CLI：自动接管父控制台，`doctor`、`status` 等输出直接显示 |
| `.weblauncher/` | 首次运行自动生成的运行时数据（exe 同级） |

```bat
weblauncher.exe doctor         :: 自检：依赖、路径、端口
weblauncher.exe install        :: 在桌面创建主入口 + 每服务快捷方式
weblauncher.exe                :: 打开窗口并驻留托盘
weblauncher.exe open dsh       :: 只打开/置前 dsh 窗口，不驻留托盘
```

> GUI 子系统的 exe 由 `cmd.exe` 启动时不会阻塞提示符，输出会稍后出现在同一个控制台里。
> 需要等待退出码或串联命令时用 `start /wait weblauncher.exe status`（PowerShell 同样适用）。

### Linux 安装

解压后是 `weblauncher`（单文件）+ `_internal/` + `assets/app.png`：

```bash
./weblauncher doctor        # 自检：会话类型、依赖、窗口控制能力、端口
./weblauncher install       # 写入 ~/.local/share/applications 与图标
./weblauncher               # 打开窗口并驻留托盘
```

`install` 只写应用菜单（GNOME 默认不显示桌面图标），不会碰 `~/Desktop`。

### 源码运行

需要 uv、Python 3.12+、Node.js，以及一个 Chromium 系浏览器（Chrome / Edge / Chromium / Brave）。
托盘由 pystray 提供（`uv sync` 已装）；Linux 还要求桌面有可用的 AppIndicator / GTK / X11 后端，
没有时 `tray` 会明确报错，CLI 不受影响。

```bash
uv sync
uv run python -m weblauncher doctor
uv run python -m weblauncher          # 前台运行托盘（Ctrl+C 退出并停服务）
uv run python -m weblauncher open dsh
```

## 命令

| 命令 | 作用 |
|---|---|
| `tray`（默认 / 双击） | 前台运行系统托盘：按服务启动/打开，Ctrl+C 退出并停全部服务 |
| `start / stop / restart / open <dsh\|jupyter\|all>` | 只操作服务；已在跑时 `start` 直接复用；`restart` 让配置变更生效 |
| `status [dsh\|jupyter\|all]` | PID、端口、URL、root_dir/内核；`--json` 输出结构化状态 |
| `doctor [dsh\|jupyter\|all]` | 依赖发现、平台后端、托盘、端口占用、每个服务的依赖；`--json` |
| `config list / get / set / unset / path` | 读写 `config.toml`，保留手写注释 |
| `jupyter kernel add / list / show / use / rename / remove` | 注册/命名/选择 Python 内核 |
| `jupyter workdir use / list / current` | 选择 Jupyter 工作目录并记住 |
| `dsh updates`（旧入口 `updates`） | 检查 dsh 与 `web` profile 插件更新；`--json` / `--panel` |
| `install / uninstall` | 创建 / 删除桌面入口（主托盘 + 每个服务） |
| `version` | 版本号 |

通用参数：`--host --port --browser --ozone --profile-dir --no-dedupe --start-timeout`。
dsh 额外接受 `--cwd --node --dsh-bin`；Jupyter 额外接受 `--root --kernel --jupyter-bin --base-url`。
`dsh updates` 额外接受 `--json` / `--panel` / `--profile` / `--timeout`。

### 托盘菜单

| 菜单项 | 作用 |
|---|---|
| dsh web / Jupyter Lab 子菜单 | 每个服务都有：打开、状态、启动、停止、重启、查看日志、打开数据目录 |
| 启动全部 / 停止全部 | 按服务 id 顺序加锁，避免交叉操作 |
| 刷新状态 | 重新读取状态并刷新菜单（外部 `start` / `stop` 后手动点一下） |
| 检查更新… | 仅 dsh：打开本地更新面板 |
| 退出（服务继续） | 只移除托盘图标 |
| 退出并停止全部服务 | 先停所有服务，再移除图标；窗口保留 |

## 检查与升级更新

```bash
weblauncher updates                 # 文本报告；有更新退出码 1
weblauncher updates --json          # 脚本消费
weblauncher updates --panel         # 打开面板，终端 Ctrl+C 结束
weblauncher updates --profile dsh-tui --timeout 60
```

- **检查对象**：`dsh` 的全局安装（从 `dsh_bin` 所在包读版本），以及
  `$DSH_HOME/profiles/<profile>`（默认 `~/.dsh/profiles/web`）`package.json` 里的直接依赖。
- **数据来源**：`npm view` / `npm outdated`，缺失时回退 `pnpm` 与
  `dsh plugin --profile <name> outdated`；代理、私有 registry、认证都沿用现有配置。
  启动器不保存 registry 凭据。
- **升级顺序**：先 dsh，再插件。开始前停止 dsh 服务（如果正在运行），结束后自动重启；
  升级 dsh 使用识别到的全局包管理器（npm / pnpm），插件通过
  `dsh plugin --profile <name> add <包>@<版本> --save-exact`，沿用 dsh 的兼容性预检。
- **前置条件**：文本检查需要 npm 或 pnpm；dsh 升级还需要能识别 dsh 所属的全局包管理器。
  用 `--dsh-bin` / `WEBLAUNCHER_DSH_BIN` 显式指定 dsh 路径时，不自动升级 dsh，面板会提示手动处理。
- **面板**：只监听 `127.0.0.1` 的随机端口，URL 带随机 token；POST 升级还要校验 token 与 Host。
  面板使用独立的 `panel-browser/` Chromium 配置，不会劫持 dsh 应用窗口。
  托盘里的面板随托盘进程存活；`updates --panel` 的面板随该终端进程存活。
- **非 registry 依赖**：`file:` / `link:` / `git+` / GitHub 简写 / tarball / `npm:` 别名不猜测更新，
  在面板里标记为跳过。
- **无法比较或安装失败**：报告会保留具体版本和命令输出；dsh 升级失败会跳过后续插件，
  单个插件失败不阻断其它插件，服务仍会尝试恢复运行。
- **升级日志**：完整命令输出追加到 `.weblauncher/upgrades.log`（超过 1 MB 轮转 `.1`）；
  面板实时日志只保留最后 600 行，避免大量 peer 警告把结尾挤掉。
- **升级后的 dsh 窗口**：服务重启会换 token，旧应用窗口可能显示 401；关掉窗口后从托盘
  「打开窗口」重新打开即可。更新面板使用独立配置，不受影响。

退出码：`0` 无更新；`1` 有更新；`2` 检查失败（至少一项完全无法检查）。

## 数据与配置

数据目录默认在**可执行文件同级的 `.weblauncher/`**（源码运行时是项目根目录），
目标不可写时回退到用户数据目录；`WEBLAUNCHER_HOME` 可强制指定。里面是：

| 文件 | 内容 |
|---|---|
| `services/<id>/state.json` | 该服务的 pid / create_time / port / url / token |
| `services/<id>/service.log` | 该服务的 stdout/stderr，含每次启动的 `[launcher] start` 标记 |
| `services/<id>/service.lock` | start/stop/restart 的跨进程互斥锁（正常结束自动删除） |
| `services/<id>/browser/` | 该服务专用的 Chromium 配置（零扩展；cookie 绑定 host:port） |
| `memory.toml` | 启动器写的选择记忆：Jupyter 工作目录、最近目录、默认内核、按目录内核 |
| `config.toml` | 手写/`config set` 的运行参数（`[launcher] [ui] [dsh] [jupyter]`） |
| `launcher.log` | 启动器动作审计；超过 1 MB 轮转为 `.1` |
| `upgrades.log` | dsh 升级任务完整日志 |
| `panel-browser/` | 更新面板的独立浏览器配置 |
| `tray.lock` / `tray.json` | 托盘单实例锁与 loopback IPC 端口/随机 token |

旧版单服务布局（根目录 `state.json` / `dsh-web.log` / `browser/`）会在首次运行时自动搬进 `services/dsh/`；旧品牌数据目录 `.dshlauncher/` 也会在首次启动时整体改名为 `.weblauncher/`。

POSIX 上运行时目录按 0700、状态/日志/配置文件按 0600 创建，避免同机其它用户读取 token。

配置优先级：**命令行参数 > 环境变量 `WEBLAUNCHER_DSH_*` > `config.toml` > 默认值**。

```toml
# .weblauncher/config.toml
[launcher]
start_timeout = 120
tray_exit_stops_services = true

[ui]
browser = "chrome"          # 或可执行文件路径
ozone = "auto"
dedupe = true

[ui.window]
width_ratio = 0.84
height_ratio = 0.86
min_width = 1024
min_height = 680

[dsh]
host = "127.0.0.1"
port = 3080
work_dir = "C:/Users/me/AppData/Local/Temp"
# node = "C:/Program Files/nodejs/node.exe"
# dsh_bin = "C:/Users/me/AppData/Roaming/npm/node_modules/@deepseek-ai/dsh/lib/bin.js"

[jupyter]
host = "127.0.0.1"
port = 8888
# root_dir = "E:/notebooks"   # 省略时用 memory.toml 里上次的目录
# kernel = "project"          # 通常用 `jupyter kernel use` 设置
base_url = "/"
start_timeout = 60
```

优先级：**CLI > 服务环境变量 > `config.toml` > `memory.toml`（选择记忆）> 默认值**。
旧版平铺在根上的 dsh/窗口字段仍可读取。

### 端口

默认 `3080`。启动前会对目标端口**真实 bind 一次**判定状态，而不是只看有没有人在连：

| 状态 | 行为 |
|---|---|
| 可用 | 直接使用 |
| 被其它进程占用 | dsh：端口上是 `dsh web` 则接管重启；否则自动换端口 |
| 系统保留（Windows 排除段） | 跳过，按 `上次用过的端口 → 配置端口 → 回退序列` 依次尝试 |

Jupyter 默认 `8888`，冲突时按 `8889 → 8890 → 18888…` 自动回退；**不会接管**手动启动的 Jupyter（那可能是你正在用的实例）。两个服务自动选端口时会互相排除对方已配置/上次使用的端口。

显式指定的端口（`--port` / `WEBLAUNCHER_DSH_PORT` / `config.toml`）**不会**被自动替换：不可用时直接报错，并给出命中的保留段与可用的替代端口。`--port 0` 交给系统分配，真实端口从启动 URL 里取回。

选中的端口写入 `state.json`，下次优先复用——浏览器 cookie 绑 `host:port`，端口稳定才不会反复要求重新授权。

### 环境变量

共享/ dsh 变量带 `WEBLAUNCHER_DSH_` 前缀，Jupyter 变量带 `WEBLAUNCHER_JUPYTER_` 前缀（Windows 不区分大小写），**空值等同未设置**。

| 变量 | 作用 | 默认值 |
|---|---|---|
| `WEBLAUNCHER_HOME` | 运行时数据目录：`config.toml`、`memory.toml`、`services/<id>/`、托盘锁都在这里 | exe 同级 `.weblauncher/`；源码运行是项目根；该位置不可写时回退用户数据目录 |
| `WEBLAUNCHER_DSH_HOST` | 服务监听地址 | `127.0.0.1` |
| `WEBLAUNCHER_DSH_PORT` | 服务端口 | `3080`；被系统保留或占用时自动回退到 `18080` 起。设为显式值即固定，不自动替换（cookie 绑 `host:port`，换端口等于重新授权） |
| `WEBLAUNCHER_DSH_CWD` | 服务工作目录；会话里 bash/文件工具的默认起步目录 | 系统临时目录（Windows 为 `%TEMP%`） |
| `WEBLAUNCHER_DSH_NODE` | node 可执行文件 | 自动发现：`PATH` → 常见安装目录 |
| `WEBLAUNCHER_DSH_BIN` | `@deepseek-ai/dsh/lib/bin.js` 的路径 | 自动发现：`which dsh` → `npm root -g` → `pnpm root -g` |
| `WEBLAUNCHER_BROWSER` | 浏览器家族名（`chrome` / `edge` / `chromium` / `brave`）或可执行文件路径 | 按 chrome → edge → chromium → brave 顺序探测 |
| `WEBLAUNCHER_OZONE` | Linux 显示后端：`auto` / `x11` / `wayland` | `auto`（Wayland 会话里 Chrome 用原生 Wayland；`x11` 强制 XWayland 以获得完整窗口控制） |
| `WEBLAUNCHER_DSH_PROFILE_DIR` | dsh 专用浏览器配置目录（零扩展窗口的数据） | `<数据目录>/services/dsh/browser` |
| `WEBLAUNCHER_NO_DEDUPE` | 设为任意非空值即不复用已有窗口，每次都新开 | 未设置（窗口存在时置前） |
| `WEBLAUNCHER_DSH_START_TIMEOUT` | 等待 dsh 就绪的秒数 | `120` |
| `WEBLAUNCHER_JUPYTER_HOST` | Jupyter 监听地址 | `127.0.0.1` |
| `WEBLAUNCHER_JUPYTER_PORT` | Jupyter 端口 | `8888`；显式值不自动替换，省略时冲突自动回退 |
| `WEBLAUNCHER_JUPYTER_ROOT` | Jupyter 工作目录（root_dir） | memory.toml 里上次的目录，否则 `~` |
| `WEBLAUNCHER_JUPYTER_KERNEL` | 新 notebook 的默认内核 id | memory.toml 里按目录/全局记忆 |
| `WEBLAUNCHER_JUPYTER_BIN` | `jupyter-lab` 可执行文件 | uv tool → PATH → `~/.local/bin` 自动发现 |
| `WEBLAUNCHER_JUPYTER_BASE_URL` | Jupyter base_url | `/` |
| `WEBLAUNCHER_JUPYTER_TOKEN` | 固定 token；省略则每次启动随机 | 未设置 |
| `WEBLAUNCHER_JUPYTER_PROFILE_DIR` | Jupyter 专用浏览器配置目录 | `<数据目录>/services/jupyter/browser` |
| `WEBLAUNCHER_JUPYTER_START_TIMEOUT` | 等待 Jupyter 就绪的秒数 | `60` |
| `WEBLAUNCHER_WIDTH_RATIO` | 默认窗口宽度占工作区的比例 | `0.84` |
| `WEBLAUNCHER_HEIGHT_RATIO` | 默认窗口高度占工作区的比例 | `0.86` |

```bat
:: cmd：临时换端口，并把数据放到别的盘
set WEBLAUNCHER_DSH_PORT=3999
set WEBLAUNCHER_HOME=D:\dsh-data
weblauncher.exe doctor
```

```powershell
# PowerShell
$env:WEBLAUNCHER_BROWSER = "edge"
.\weblauncher.exe open dsh
```

要点：

- 变量只在**进程启动时**读取。改完 `HOST` / `PORT` / `CWD` 要 `weblauncher.exe restart dsh`（Jupyter 对应 `restart jupyter`）才对运行中的服务生效。
- 与 `config.toml` 同名项冲突时，环境变量优先；`[ui.window]` 的 `min_width` / `min_height` 只能写在 `config.toml` 里。
- 子进程（node、jupyter、浏览器）拿到的是净化过的环境：去掉了指向本程序 `_internal/` 的 `PATH` 项，防止对方加载到启动器自带的 DLL。

## Jupyter Lab

Jupyter 由 `uv tool` 安装，启动器只负责发现和托管，不捆绑 Python 环境：

```bash
uv tool install jupyterlab
weblauncher doctor                 # 确认 jupyter-lab / 环境 / root_dir
weblauncher jupyter workdir use E:/develop_self/FinMate
weblauncher jupyter kernel add --dir E:/develop_self/FinMate --display-name "FinMate"
weblauncher jupyter kernel use finmate
weblauncher start jupyter          # 或直接 weblauncher open jupyter
```

- **工作目录**：`--ServerApp.root_dir`，决定文件浏览器范围；`jupyter workdir use` 立即持久化，最近 10 个目录记在 `memory.toml`。
- **内核**：注册的是目标解释器的绝对路径；目标 venv 必须能 `import ipykernel`，缺失时 `kernel add` 会给出命令，`--install-ipykernel` 可显式调用 `uv pip install`。
- **命名**：`--name` 是 kernelspec id（小写字母/数字/._-），`--display-name` 是 Jupyter 里看到的名字，可写中文。
- **默认内核**：`kernel use` 写入 `memory.toml`，服务启动时通过 `--MappingKernelManager.default_kernel_name` 注入；只影响新建 notebook，已有 notebook 保持自己的 kernel。
- **按目录记忆**：从哪个工作目录选的 kernel 会被记住；再次切回该目录时自动恢复（`[jupyter] remember_per_workdir = false` 可关）。
- **token**：默认每次启动随机生成，通过子进程环境变量传入，不出现在命令行；日志里 Jupyter 会打码成 `?token=...`，启动器自己拼 URL。
- **停止**：先 `POST /api/shutdown`（内核一起退），超时才杀进程树。
- **端口**：默认 8888，冲突自动回退；不会接管手动启动的 Jupyter。

## 平台差异

| 能力 | Windows | Linux / X11 会话 | Linux / Wayland 会话 |
|---|---|---|---|
| 服务脱离终端 | `DETACHED_PROCESS` + breakaway | `start_new_session` | `start_new_session` |
| 系统托盘 | pystray `_win32` | pystray `_xorg`（`python-xlib`） | `AppIndicator` / `GTK`，或 XWayland（需 `DISPLAY`） |
| 窗口枚举 / 置前 | Win32 | EWMH（`_NET_CLIENT_LIST` / `_NET_ACTIVE_WINDOW`） | 默认不可用；`--ozone x11` 时与 X11 相同 |
| 尺寸 / 位置纠正 | 工作区 + `SetWindowPos` | `_NET_WORKAREA` + `XMoveResizeWindow` | 默认只传 `--window-size`；`--ozone x11` 时与 X11 相同 |
| 已有窗口去重 | 枚举 + 置前 | 枚举 + 置前 | 默认无法置前，每次 `open` 新开窗口 |
| 桌面入口 | `.lnk`（PowerShell COM） | `.desktop`（应用菜单） | `.desktop`（应用菜单） |
| 打开日志 | `os.startfile` | `xdg-open` | `xdg-open` |

macOS 上 `install` 不自动创建桌面入口（会明确报不支持，Finder 别名无法携带 `-m weblauncher` 参数）；
直接运行 `weblauncher tray`，或手动为可执行文件创建别名。

Wayland 协议本身不提供跨应用枚举/移动窗口的接口，所以默认让 Chrome 走原生 Wayland（渲染、缩放最好）；
需要 Windows 一样的置前与尺寸纠正时用 `--ozone x11`（Chrome 走 XWayland）：

```bash
weblauncher open dsh --ozone x11
# 或写进 .weblauncher/config.toml
# [ui]
# ozone = "x11"
```

无扩展窗口依赖 Chromium 的 `--app`，Firefox / Safari 没有等价能力，`doctor` 会直接报错。

## 目录结构

```
src/weblauncher/
  paths.py config.py memory.py     共享：数据目录、配置、选择记忆
  ports.py process.py supervisor.py 共享：端口、进程树、生命周期
  discovery.py browser.py splash.py 共享：浏览器窗口
  services/base.py                 服务适配器契约
  services/registry.py             服务注册表（唯一出现服务名的地方）
  services/dsh/                    dsh 适配器、更新/升级/面板
  services/jupyter/                Jupyter 适配器、内核、工作目录
  tray/ install/ platform/         托盘、桌面入口、平台后端
docs/                     架构说明
tests/                    纯逻辑单测
packaging/                PyInstaller 入口、spec、应用图标
scripts/build.py          打包 + 部署
Makefile                  任务入口（检查 / 跑服务 / 打包 / 清理）
app/                      部署目录：weblauncher.exe + _internal/ + .weblauncher/ 数据
.build/                   PyInstaller 中间产物与 dist（生成物，gitignore）
.cache/                   pytest / ruff 缓存（gitignore）
```

`src/` 布局 + `uv sync` 的 editable 安装意味着 `python -m weblauncher` 在任何工作目录都能用，
源码模式下的数据目录仍然落在项目根（向上查找 `pyproject.toml`，与包所在层级无关）。

## 架构

进程模型、模块分层、状态/日志/IPC/锁与扩展点见 [`docs/architecture.md`](docs/architecture.md)。

## 开发入口（make）

环境与依赖仍然由 uv 独立管理（`uv sync` / `uv add` / `uv lock`），`make` 只做任务，不包装 uv：

```bash
make            # 列出全部目标
make env        # 解释器 / ruff / pytest / pyinstaller 版本
make check      # lint + format --check + test
make smoke      # start all → status all → stop all，真机验证端口与就绪
make build      # 打包并部署到 app/
```

其余目标见 `make help`：`format`、`test ARGS="-k port"`、`start` / `stop` / `restart` /
`status` / `doctor` / `tray` / `open`、`jupyter`、`deploy`、`clean`、`distclean`。
服务选择用 `SERVICE=dsh|jupyter|all`，例如 `make start SERVICE=jupyter`。

Windows 上用 MSYS2 自带的 make：`pacman -S make`，再把 `C:\msys64\usr\bin` **追加**到用户 `PATH`
（不要前置——那会让所有终端优先用上 MSYS2 的 `find` / `sort` / `tar`）。同一目录下的 `sh`、`git`、
`grep` 一并可用，recipe 里的 POSIX 命令才有得跑；只有 `make.exe` 而没有 `sh` 时，make 会退回
`cmd.exe`，`.venv/Scripts/python.exe` 这种正斜杠路径会被 cmd 截断。

> `make` 的 recipe 直接调用 `.venv` 里的解释器，所以环境仍由 uv 管理：先 `uv sync`，再 `make ...`。

Linux / macOS 用发行版的 `make` 即可。

## 构建

```bash
uv sync
make build          # PyInstaller onedir → .build/dist，再同步到 app/
make deploy         # 只重新部署（复用上次构建）
```

等价的手写命令：`uv run python scripts/build.py [--skip-build]`。

产物是 `.build/dist/weblauncher/`：单个 `weblauncher.exe`（Windows）/ `weblauncher`（Linux）
+ `_internal/`（约 30 MB）+ `assets/app.png`。
必须在目标平台上各自构建（PyInstaller 不交叉编译）；`app/` 是部署目录，`app/.weblauncher/`
的数据不会被构建清理。

> 部署前先退出托盘（右键 → 退出并停止服务）、关掉应用窗口：窗口打开时 `_internal` 里的 DLL 被占用，
> 覆盖会失败（脚本会给出这条提示）。

## 测试与检查

```bash
uv run pytest            # 纯逻辑单测
uv run ruff check .      # lint
uv run ruff format .     # 格式化
```

只覆盖纯逻辑：token/URL、窗口几何、配置/记忆优先级、依赖发现、kernelspec 注册与删除、Jupyter HTTP 就绪/关闭、跨服务端口排除、托盘单实例/IPC/编排、状态快照、JSON 输出与安装器。

## 故障排查

- **窗口里是 401 / Jupyter 提示 token 失效**：服务重启过而窗口还拿着旧 token —— 关掉窗口，再点托盘「打开窗口」或重新双击；Jupyter 的 token 默认每次启动都换。
- **双击后托盘区看不到图标**：Windows 11 默认把新图标收进溢出区，点任务栏的 `^` 固定一次即可；
  Linux 需要桌面提供 AppIndicator / GTK / X11 后端，`doctor` 的「托盘」与「托盘进程」行会给出后端、PID 与 IPC 端口。
- **托盘菜单里的状态没跟着变**：菜单标签只在托盘动作完成后刷新；外部 `start` / `stop` 之后点「刷新状态」即可。
  「服务状态」弹窗每次点击都重新读取；tooltip 每 2 秒自动更新。
- **终端里中文乱码**：输出编码跟随控制台代码页——936（GBK）控制台保持默认编码，65001 才用 UTF-8；显式设置 `PYTHONIOENCODING` / `PYTHONUTF8` 时以你的设置为准。PowerShell 5.1 默认 936，想让会话统一 UTF-8 可在 `$PROFILE` 里设 `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)`。
- **端口被占或被系统保留**：`doctor` 的「<服务> · 端口」行会区分 `被占用` / `系统保留（区间）`，占用时还会打印占用者的 pid 与命令行。默认端口会自动回退；显式 `--port` 撞上保留段会直接报错并给出可换端口，`netsh interface ipv4 show excludedportrange protocol=tcp` 可查看全部保留段。
- **`dsh` 升级后行为不对**：`weblauncher restart dsh`。
- **Jupyter 内核没有出现在列表里**：`weblauncher jupyter kernel list`；确认 kernelspec 的 Python 路径还在，`kernel add` 的目标 venv 要能 `import ipykernel`。
- **Jupyter 默认内核没生效**：`kernel use` 后要 `weblauncher restart jupyter`；它只影响新建 notebook，已有 notebook 保持自己的 metadata。
- **Jupyter 端口被手动实例占用**：启动器不会接管，会自动换到 8889/8890/18888；要固定端口用 `--port`。
- **找不到 jupyter-lab**：`doctor` 打印解析路径；用 `WEBLAUNCHER_JUPYTER_BIN` 或 `--jupyter-bin` 指定，确信用的是 `uv tool list` 里那个安装。
- **找不到依赖**：`doctor` 逐项列出 node / dsh / 浏览器，缺哪个补哪个，或用 `--node / --dsh-bin / --browser` 指定。
- **Linux 上点了图标窗口没有置前**：当前是原生 Wayland，属协议限制；用 `--ozone x11` 重开。切换前先关掉旧窗口（Chrome 单实例会忽略新启动参数）。
- **双击时提示端口占用**：若 3080 上是手动启动的 `dsh web`，`open dsh` 会停止它并接管重启（token 只存在于它的 stdout，无法复用）；
  占用者是其它程序时才会报错。
- **Linux 上 `dsh` 找不到**：`doctor` 会打印实际解析路径；`~/.local/bin/dsh` 符号链接、npm/pnpm 全局目录都已覆盖，仍失败时用 `WEBLAUNCHER_DSH_BIN` 指定 `lib/bin.js`。
