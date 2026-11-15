# Changelog

## 0.3.0

- 双击进入系统托盘：打开 dsh 窗口后常驻，右键菜单承载打开/停止/重启/刷新/日志/数据目录/退出。
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
