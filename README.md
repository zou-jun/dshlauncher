# dshlauncher

托管 `dsh web` 服务，并在**独立的 Chromium 用户配置**里打开一个无浏览器扩展的应用窗口。

- 服务以分离进程运行：关掉终端、关掉 dsh 窗口都不影响它；只有托盘菜单的「退出并停止服务」会显式停掉
- 双击进入系统托盘：窗口照常打开，图标常驻；右键菜单里能打开窗口、停/重启服务、看日志
- 服务启动慢时先打开本地过场页，就绪后自动跳转；托盘状态显示「启动中」
- 窗口用 `--user-data-dir` + `--app`：没有地址栏，也不会带上你日常浏览器的那堆扩展
- `start / stop / restart / status` 齐全，`doctor` 打印解析到的依赖、数据目录和端口占用
- Windows 完整支持；Linux 完整支持（X11 / XWayland，见「平台差异」）；macOS 尽力而为

## 安装

### Windows 打包版

解压后的目录里有：

只有一个 `dshlauncher.exe`（GUI 子系统），按有没有参数切换形态：

| 启动方式 | 行为 |
|---|---|
| 双击 exe / 桌面快捷方式 | 等同 `tray`：确保服务在跑、打开窗口，并常驻系统托盘 |
| 终端里带参数 | CLI：自动接管父控制台，`doctor`、`status` 等输出直接显示 |
| `.dshlauncher/` | 首次运行自动生成的运行时数据（exe 同级） |

```bat
dshlauncher.exe doctor         :: 自检：依赖、路径、端口
dshlauncher.exe install        :: 在桌面创建 dsh.lnk
dshlauncher.exe                :: 打开窗口并驻留托盘
dshlauncher.exe open           :: 只打开/置前窗口，不驻留托盘
```

> GUI 子系统的 exe 由 `cmd.exe` 启动时不会阻塞提示符，输出会稍后出现在同一个控制台里。
> 需要等待退出码或串联命令时用 `start /wait dshlauncher.exe status`（PowerShell 同样适用）。

### Linux 安装

解压后是 `dshlauncher`（单文件）+ `_internal/` + `assets/app.png`：

```bash
./dshlauncher doctor        # 自检：会话类型、依赖、窗口控制能力、端口
./dshlauncher install       # 写入 ~/.local/share/applications 与图标
./dshlauncher               # 打开窗口并驻留托盘
```

`install` 只写应用菜单（GNOME 默认不显示桌面图标），不会碰 `~/Desktop`。

### 源码运行

需要 uv、Python 3.12+、Node.js，以及一个 Chromium 系浏览器（Chrome / Edge / Chromium / Brave）。
托盘由 pystray 提供（`uv sync` 已装）；Linux 还要求桌面有可用的 AppIndicator / GTK / X11 后端，
没有时 `tray` 会明确报错，CLI 不受影响。

```bash
uv sync
uv run python -m dshlauncher doctor
uv run python -m dshlauncher          # 前台运行托盘（Ctrl+C 退出并停服务）
uv run python -m dshlauncher open
```

## 命令

| 命令 | 作用 |
|---|---|
| `tray`（默认 / 双击） | 前台运行系统托盘：确保服务在跑、打开/置前窗口；Ctrl+C 退出并停服务 |
| `open` | 只确保服务并打开/置前窗口，不启动托盘 |
| `start` / `stop` / `restart` | 只操作服务；已在跑时 `start` 直接复用，显式换端口会先停掉旧实例；`dsh` 升级后用 `restart` |
| `status` | 服务 PID、端口、token URL、路径；`--json` 输出结构化状态 |
| `doctor` | 依赖发现结果、平台后端、托盘后端与进程、端口占用者、配置来源；`--json` 输出键值列表 |
| `install` / `uninstall` | 创建 / 删除桌面入口 |
| `version` | 版本号 |

通用参数：`--host --port --cwd --node --dsh-bin --browser --ozone --profile-dir --no-dedupe --start-timeout`。

### 托盘菜单

| 菜单项 | 作用 |
|---|---|
| 打开窗口 | 确保服务在跑并打开/置前窗口；左键单击图标等价于此 |
| 服务状态：运行中/未运行… | 点击弹窗显示 PID、端口、URL、工作目录、数据目录与日志路径 |
| 停止服务 / 重启服务 | 直接操作 dsh 服务 |
| 刷新状态 | 重新读取状态并刷新菜单（外部 `start` / `stop` 后手动点一下） |
| 查看日志 / 打开数据目录 | 打开 `dsh-web.log` / 数据目录 |
| 退出并停止服务 | 先停 dsh，再移除托盘图标；已打开的窗口保留 |

## 数据与配置

数据目录默认在**可执行文件同级的 `.dshlauncher/`**（源码运行时是项目根目录），
目标不可写时回退到用户数据目录；`DSHLAUNCHER_HOME` 可强制指定。里面是：

| 文件 | 内容 |
|---|---|
| `state.json` | 服务 pid / create_time / port / url |
| `dsh-web.log` | 服务输出，含每次启动的 `[launcher] start` 标记与 token URL |
| `launcher.log` | 启动器动作审计；超过 1 MB 轮转为 `.1` |
| `browser/` | 专用浏览器配置（零扩展；cookie 绑定 host:port） |
| `tray.lock` / `tray.json` | 托盘单实例锁与 loopback IPC 端口/随机 token（正常退出时删除，被强杀后下次启动自动清理） |
| `config.toml` | 可选配置文件 |

配置优先级：**命令行参数 > 环境变量 `DSHLAUNCHER_*` > `config.toml` > 默认值**。

```toml
# .dshlauncher/config.toml
# port = 18080              # 省略则自动挑（上次用过的 → 3080 → 18080 起）
host = "127.0.0.1"
work_dir = "C:/Users/me/AppData/Local/Temp"
browser = "chrome"          # 或可执行文件路径
# node = "C:/Program Files/nodejs/node.exe"
# dsh_bin = "C:/Users/me/AppData/Roaming/npm/node_modules/@deepseek-ai/dsh/lib/bin.js"
dedupe = true

[window]
width_ratio = 0.84
height_ratio = 0.86
min_width = 1024
min_height = 680
```

### 端口

默认 `3080`。启动前会对目标端口**真实 bind 一次**判定状态，而不是只看有没有人在连：

| 状态 | 行为 |
|---|---|
| 可用 | 直接使用 |
| 被其它进程占用 | 端口上是 `dsh web` 则接管重启，否则报错并打印占用者 |
| 系统保留（Windows 排除段） | 跳过，按 `上次用过的端口 → 3080 → 18080 → 18081…` 依次尝试 |

显式指定的端口（`--port` / `DSHLAUNCHER_PORT` / `config.toml`）**不会**被自动替换：不可用时直接报错，并给出命中的保留段与可用的替代端口。`--port 0` 交给系统分配，真实端口从启动 URL 里取回。

选中的端口写入 `state.json`，下次优先复用——浏览器 cookie 绑 `host:port`，端口稳定才不会反复要求重新授权。

### 环境变量

全部带 `DSHLAUNCHER_` 前缀（Windows 不区分大小写），**空值等同未设置**。

| 变量 | 作用 | 默认值 |
|---|---|---|
| `DSHLAUNCHER_HOME` | 运行时数据目录：`state.json`、两份日志、浏览器 profile 都在这里 | exe 同级 `.dshlauncher/`；源码运行是项目根；该位置不可写时回退用户数据目录 |
| `DSHLAUNCHER_HOST` | 服务监听地址 | `127.0.0.1` |
| `DSHLAUNCHER_PORT` | 服务端口 | `3080`；被系统保留或占用时自动回退到 `18080` 起。设为显式值即固定，不自动替换（cookie 绑 `host:port`，换端口等于重新授权） |
| `DSHLAUNCHER_CWD` | 服务工作目录；会话里 bash/文件工具的默认起步目录 | 系统临时目录（Windows 为 `%TEMP%`） |
| `DSHLAUNCHER_NODE` | node 可执行文件 | 自动发现：`PATH` → 常见安装目录 |
| `DSHLAUNCHER_DSH_BIN` | `@deepseek-ai/dsh/lib/bin.js` 的路径 | 自动发现：`which dsh` → `npm root -g` → `pnpm root -g` |
| `DSHLAUNCHER_BROWSER` | 浏览器家族名（`chrome` / `edge` / `chromium` / `brave`）或可执行文件路径 | 按 chrome → edge → chromium → brave 顺序探测 |
| `DSHLAUNCHER_OZONE` | Linux 显示后端：`auto` / `x11` / `wayland` | `auto`（Wayland 会话里 Chrome 用原生 Wayland；`x11` 强制 XWayland 以获得完整窗口控制） |
| `DSHLAUNCHER_PROFILE_DIR` | 专用浏览器配置目录（零扩展窗口的数据） | `<数据目录>/browser` |
| `DSHLAUNCHER_NO_DEDUPE` | 设为任意非空值即不复用已有窗口，每次都新开 | 未设置（窗口存在时置前） |
| `DSHLAUNCHER_START_TIMEOUT` | 等待服务就绪的秒数 | `120` |
| `DSHLAUNCHER_WIDTH_RATIO` | 默认窗口宽度占工作区的比例 | `0.84` |
| `DSHLAUNCHER_HEIGHT_RATIO` | 默认窗口高度占工作区的比例 | `0.86` |

```bat
:: cmd：临时换端口，并把数据放到别的盘
set DSHLAUNCHER_PORT=3999
set DSHLAUNCHER_HOME=D:\dsh-data
dshlauncher.exe doctor
```

```powershell
# PowerShell
$env:DSHLAUNCHER_BROWSER = "edge"
.\dshlauncher.exe open
```

要点：

- 变量只在**进程启动时**读取。改完 `HOST` / `PORT` / `CWD` 要 `dshlauncher.exe restart` 才对运行中的服务生效。
- 与 `config.toml` 同名项冲突时，环境变量优先；`[window]` 的 `min_width` / `min_height` 只能写在 `config.toml` 里。
- 子进程（node、浏览器）拿到的是净化过的环境：去掉了指向本程序 `_internal/` 的 `PATH` 项，防止对方加载到启动器自带的 DLL。

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

macOS 上 `install` 不自动创建桌面入口（会明确报不支持，Finder 别名无法携带 `-m dshlauncher` 参数）；
直接运行 `dshlauncher tray`，或手动为可执行文件创建别名。

Wayland 协议本身不提供跨应用枚举/移动窗口的接口，所以默认让 Chrome 走原生 Wayland（渲染、缩放最好）；
需要 Windows 一样的置前与尺寸纠正时用 `--ozone x11`（Chrome 走 XWayland）：

```bash
dshlauncher open --ozone x11
# 或写进 .dshlauncher/config.toml
# ozone = "x11"
```

无扩展窗口依赖 Chromium 的 `--app`，Firefox / Safari 没有等价能力，`doctor` 会直接报错。

## 目录结构

```
src/dshlauncher/          源码包（platform/、install/、tray/ 是子包）
docs/                     架构说明
tests/                    纯逻辑单测
packaging/                PyInstaller 入口、spec、应用图标
scripts/build.py          打包 + 部署
Makefile                  任务入口（检查 / 跑服务 / 打包 / 清理）
app/                      部署目录：dshlauncher.exe + _internal/ + .dshlauncher/ 数据
.build/                   PyInstaller 中间产物与 dist（生成物，gitignore）
.cache/                   pytest / ruff 缓存（gitignore）
```

`src/` 布局 + `uv sync` 的 editable 安装意味着 `python -m dshlauncher` 在任何工作目录都能用，
源码模式下的数据目录仍然落在项目根（向上查找 `pyproject.toml`，与包所在层级无关）。

## 架构

进程模型、模块分层、状态/日志/IPC/锁与扩展点见 [`docs/architecture.md`](docs/architecture.md)。

## 开发入口（make）

环境与依赖仍然由 uv 独立管理（`uv sync` / `uv add` / `uv lock`），`make` 只做任务，不包装 uv：

```bash
make            # 列出全部目标
make env        # 解释器 / ruff / pytest / pyinstaller 版本
make check      # lint + format --check + test
make smoke      # start → status → stop，真机验证端口与就绪
make build      # 打包并部署到 app/
```

其余目标见 `make help`：`format`、`test ARGS="-k port"`、`start` / `stop` / `restart` /
`status` / `doctor` / `tray` / `open`、`deploy`、`clean`、`distclean`。

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

产物是 `.build/dist/dshlauncher/`：单个 `dshlauncher.exe`（Windows）/ `dshlauncher`（Linux）
+ `_internal/`（约 30 MB）+ `assets/app.png`。
必须在目标平台上各自构建（PyInstaller 不交叉编译）；`app/` 是部署目录，`app/.dshlauncher/`
的数据不会被构建清理。

> 部署前先退出托盘（右键 → 退出并停止服务）、关掉应用窗口：窗口打开时 `_internal` 里的 DLL 被占用，
> 覆盖会失败（脚本会给出这条提示）。

## 测试与检查

```bash
uv run pytest            # 纯逻辑单测
uv run ruff check .      # lint
uv run ruff format .     # 格式化
```

只覆盖纯逻辑：token URL、窗口几何、配置优先级、依赖发现、托盘单实例/IPC/编排、状态快照、JSON 输出与安装器。

## 故障排查

- **窗口里是 401**：服务重启过而窗口还拿着旧 token —— 关掉窗口，再点托盘「打开窗口」或重新双击。
- **双击后托盘区看不到图标**：Windows 11 默认把新图标收进溢出区，点任务栏的 `^` 固定一次即可；
  Linux 需要桌面提供 AppIndicator / GTK / X11 后端，`doctor` 的「托盘」与「托盘进程」行会给出后端、PID 与 IPC 端口。
- **托盘菜单里的状态没跟着变**：菜单标签只在托盘动作完成后刷新；外部 `start` / `stop` 之后点「刷新状态」即可。
  「服务状态」弹窗每次点击都重新读取；tooltip 每 2 秒自动更新。
- **终端里中文乱码**：输出编码跟随控制台代码页——936（GBK）控制台保持默认编码，65001 才用 UTF-8；显式设置 `PYTHONIOENCODING` / `PYTHONUTF8` 时以你的设置为准。PowerShell 5.1 默认 936，想让会话统一 UTF-8 可在 `$PROFILE` 里设 `[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)`。
- **端口被占或被系统保留**：`doctor` 的「端口」行会区分 `被占用` / `系统保留（区间）`，占用时还会打印占用者的 pid 与命令行。默认端口会自动回退；显式 `--port` 撞上保留段会直接报错并给出可换端口，`netsh interface ipv4 show excludedportrange protocol=tcp` 可查看全部保留段。
- **`dsh` 升级后行为不对**：`restart`。
- **找不到依赖**：`doctor` 逐项列出 node / dsh / 浏览器，缺哪个补哪个，或用 `--node / --dsh-bin / --browser` 指定。
- **Linux 上点了图标窗口没有置前**：当前是原生 Wayland，属协议限制；用 `--ozone x11` 重开。切换前先关掉旧窗口（Chrome 单实例会忽略新启动参数）。
- **双击时提示端口占用**：若 3080 上是手动启动的 `dsh web`，`open` 会停止它并接管重启（token 只存在于它的 stdout，无法复用）；
  占用者是其它程序时才会报错。
- **Linux 上 `dsh` 找不到**：`doctor` 会打印实际解析路径；`~/.local/bin/dsh` 符号链接、npm/pnpm 全局目录都已覆盖，仍失败时用 `DSHLAUNCHER_DSH_BIN` 指定 `lib/bin.js`。
