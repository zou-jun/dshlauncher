# dshlauncher

托管 `dsh web` 服务，并在**独立的 Chromium 用户配置**里打开一个无浏览器扩展的应用窗口。

- 服务以分离进程运行：关掉终端、关掉启动器都不影响它
- 窗口用 `--user-data-dir` + `--app`：没有地址栏，也不会带上你日常浏览器的那堆扩展
- `start / stop / restart / status` 齐全，`doctor` 打印解析到的依赖、数据目录和端口占用
- Windows 完整支持；Linux 完整支持（X11 / XWayland，见「平台差异」）；macOS 尽力而为

## 安装

### Windows 打包版

解压后的目录里有：

只有一个 `dshlauncher.exe`（GUI 子系统），按有没有参数切换形态：

| 启动方式 | 行为 |
|---|---|
| 双击 exe / 快捷方式（无参数） | 等同 `open`：确保服务在跑并打开窗口，不闪黑窗 |
| 终端里带参数 | CLI：自动接管父控制台，`doctor`、`status` 等输出直接显示 |
| `.dshlauncher/` | 首次运行自动生成的运行时数据（exe 同级） |

```bat
dshlauncher.exe doctor         :: 自检：依赖、路径、端口
dshlauncher.exe install        :: 在桌面创建 dsh.lnk / dsh 控制台.lnk
dshlauncher.exe                :: 等同 open
```

> GUI 子系统的 exe 由 `cmd.exe` 启动时不会阻塞提示符，输出会稍后出现在同一个控制台里。
> 需要等待退出码或串联命令时用 `start /wait dshlauncher.exe status`（PowerShell 同样适用）。

### Linux 安装

解压后是 `dshlauncher`（单文件）+ `_internal/` + `assets/app.png`：

```bash
./dshlauncher doctor        # 自检：会话类型、依赖、窗口控制能力、端口
./dshlauncher install       # 写入 ~/.local/share/applications 与图标
./dshlauncher               # 等同 open
```

`install` 只写应用菜单（GNOME 默认不显示桌面图标），不会碰 `~/Desktop`。

### 源码运行

需要 uv、Python 3.12+、Node.js，以及一个 Chromium 系浏览器（Chrome / Edge / Chromium / Brave）。
`ui` 面板需要 tkinter：uv 管理的 Python 自带；系统 Python 需另装（Arch `tk` / Debian `python3-tk`）。

```bash
uv sync
uv run python -m dshlauncher doctor
uv run python -m dshlauncher open
```

## 命令

| 命令 | 作用 |
|---|---|
| `open`（默认） | 确保服务在跑，然后打开或置前窗口 |
| `start` / `stop` / `restart` | 只操作服务；`dsh` 升级后用 `restart` |
| `status` | 服务 PID、端口、token URL、路径 |
| `doctor` | 依赖发现结果、平台后端、端口占用者、配置来源 |
| `ui` | tkinter 控制面板（缺 tk 时自动退化为终端菜单） |
| `install` / `uninstall` | 创建 / 删除桌面入口 |
| `version` | 版本号 |

通用参数：`--host --port --cwd --node --dsh-bin --browser --ozone --profile-dir --no-dedupe --start-timeout`。

## 数据与配置

数据目录默认在**可执行文件同级的 `.dshlauncher/`**（源码运行时是项目根目录），
目标不可写时回退到用户数据目录；`DSHLAUNCHER_HOME` 可强制指定。里面是：

| 文件 | 内容 |
|---|---|
| `state.json` | 服务 pid / create_time / port / url |
| `dsh-web.log` | 服务输出，含每次启动的 `[launcher] start` 标记与 token URL |
| `launcher.log` | 启动器动作审计 |
| `browser/` | 专用浏览器配置（零扩展；cookie 绑定 host:port） |
| `config.toml` | 可选配置文件 |

配置优先级：**命令行参数 > 环境变量 `DSHLAUNCHER_*` > `config.toml` > 默认值**。

```toml
# .dshlauncher/config.toml
port = 3080
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

### 环境变量

全部带 `DSHLAUNCHER_` 前缀（Windows 不区分大小写），**空值等同未设置**。

| 变量 | 作用 | 默认值 |
|---|---|---|
| `DSHLAUNCHER_HOME` | 运行时数据目录：`state.json`、两份日志、浏览器 profile 都在这里 | exe 同级 `.dshlauncher/`；源码运行是项目根；该位置不可写时回退用户数据目录 |
| `DSHLAUNCHER_HOST` | 服务监听地址 | `127.0.0.1` |
| `DSHLAUNCHER_PORT` | 服务端口 | `3080`（cookie 绑 `host:port`，换端口等于重新授权） |
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
| 窗口枚举 / 置前 | Win32 | EWMH（`_NET_CLIENT_LIST` / `_NET_ACTIVE_WINDOW`） | 默认不可用；`--ozone x11` 时与 X11 相同 |
| 尺寸 / 位置纠正 | 工作区 + `SetWindowPos` | `_NET_WORKAREA` + `XMoveResizeWindow` | 默认只传 `--window-size`；`--ozone x11` 时与 X11 相同 |
| 已有窗口去重 | 枚举 + 置前 | 枚举 + 置前 | 默认无法置前，每次 `open` 新开窗口 |
| 桌面入口 | `.lnk`（PowerShell COM） | `.desktop`（应用菜单） | `.desktop`（应用菜单） |
| 打开日志 | `os.startfile` | `xdg-open` | `xdg-open` |

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
src/dshlauncher/          源码包（platform/ 与 install/ 是两个子包）
tests/                    纯逻辑单测
packaging/                PyInstaller 入口、spec、应用图标
scripts/build.py          打包 + 部署
app/                      部署目录：dshlauncher.exe + _internal/ + .dshlauncher/ 数据
.build/                   PyInstaller 中间产物与 dist（生成物，gitignore）
.cache/                   pytest / ruff 缓存（gitignore）
```

`src/` 布局 + `uv sync` 的 editable 安装意味着 `python -m dshlauncher` 在任何工作目录都能用，
源码模式下的数据目录仍然落在项目根（向上查找 `pyproject.toml`，与包所在层级无关）。

## 构建

```bash
uv sync
uv run python scripts/build.py              # PyInstaller onedir → .build/dist，再同步到 app/
uv run python scripts/build.py --skip-build # 只重新部署
```

产物是 `.build/dist/dshlauncher/`：单个 `dshlauncher.exe`（Windows）/ `dshlauncher`（Linux）
+ `_internal/`（约 30 MB）+ `assets/app.png`。
必须在目标平台上各自构建（PyInstaller 不交叉编译）；`app/` 是部署目录，`app/.dshlauncher/`
的数据不会被构建清理。

> 部署前先关掉应用窗口、`stop` 服务：窗口打开时 `_internal` 里的 DLL 被占用，
> 覆盖会失败（脚本会给出这条提示）。

## 测试与检查

```bash
uv run pytest            # 纯逻辑单测
uv run ruff check .      # lint
uv run ruff format .     # 格式化
```

只覆盖纯逻辑：token URL 的标记过滤、窗口几何钳制、配置优先级、依赖候选解析。

## 故障排查

- **窗口里是 401**：服务重启过而窗口还拿着旧 token —— 关掉窗口重新点图标。
- **端口被占**：`doctor` 会打印占用者的 pid 与命令行；先停掉那个实例，或换 `--port`。
- **`dsh` 升级后行为不对**：`restart`。
- **找不到依赖**：`doctor` 逐项列出 node / dsh / 浏览器，缺哪个补哪个，或用 `--node / --dsh-bin / --browser` 指定。
- **Linux 上点了图标窗口没有置前**：当前是原生 Wayland，属协议限制；用 `--ozone x11` 重开。切换前先关掉旧窗口（Chrome 单实例会忽略新启动参数）。
- **Linux 上 `dsh` 找不到**：`doctor` 会打印实际解析路径；`~/.local/bin/dsh` 符号链接、npm/pnpm 全局目录都已覆盖，仍失败时用 `DSHLAUNCHER_DSH_BIN` 指定 `lib/bin.js`。
