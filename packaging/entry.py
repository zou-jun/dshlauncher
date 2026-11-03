"""PyInstaller 入口脚本（窗口化与命令行两个 exe 共用）。"""

from dshlauncher.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
