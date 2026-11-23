# dshlauncher 的任务入口。
#
# 依赖与环境由 uv 独立管理（uv sync / uv add / uv lock），这里不包装 uv：
# 所有 recipe 直接调用 .venv 里的解释器，环境没建好时先自己 `uv sync`。

ifeq ($(OS),Windows_NT)
VENV_PY := .venv/Scripts/python.exe
else
VENV_PY := .venv/bin/python
endif

PY   := $(VENV_PY)
CLI  := $(PY) -m dshlauncher
ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help env lint format fmt-check test check open start stop restart status doctor updates tray smoke build deploy clean distclean

help:  ## 列出全部目标
	@$(PY) -c "import pathlib,re;[print(f'  {m[1]:<10}{m[2]}') for m in (re.match(r'^([a-z][a-z-]*):.*?##\s*(.+)', l.rstrip()) for l in pathlib.Path('Makefile').read_text('utf-8').splitlines()) if m]"

env:  ## 打印解释器与工具版本（不安装任何东西）
	@$(PY) -c "import sys;print('python      ', sys.version.split()[0], sys.executable)"
	@$(PY) -m ruff --version 2>&1 || echo "ruff         未安装（uv sync 会装 dev 组）"
	@$(PY) -m pytest --version 2>&1 | head -1 || echo "pytest       未安装（uv sync 会装 dev 组）"
	@$(PY) -c "import importlib.metadata as m;print('pyinstaller ', m.version('pyinstaller'))" 2>&1 || echo "pyinstaller  未安装（打包时需要）"

lint:  ## ruff check .
	@$(PY) -m ruff check .

format:  ## ruff format .（写盘）
	@$(PY) -m ruff format .

fmt-check:  ## ruff format --check .
	@$(PY) -m ruff format --check .

test:  ## 跑单测；可透传：make test ARGS="-k port -q"
	@$(PY) -m pytest $(ARGS)

check: lint fmt-check test  ## 提交前一条命令

open:  ## 确保服务在跑并打开窗口（不常驻托盘）
	@$(CLI) open

start:  ## 只启动服务
	@$(CLI) start

stop:  ## 停止服务
	@$(CLI) stop

restart:  ## 重启服务（dsh 升级后用）
	@$(CLI) restart

status:  ## 查看服务 PID / 端口 / token URL
	@$(CLI) status

doctor:  ## 依赖发现与端口自检
	@$(CLI) doctor

updates:  ## 检查 dsh / 插件更新；ARGS="--json" 或 ARGS="--panel"
	@$(CLI) updates $(ARGS)

tray:  ## 前台运行系统托盘（双击 exe 的等价形态，Ctrl+C 退出）
	@$(CLI) tray

smoke:  ## 真机冒烟：start → status → stop
	@$(CLI) start
	@$(CLI) status
	@$(CLI) stop

build:  ## PyInstaller 打包并部署到 app/
	@$(PY) scripts/build.py

deploy:  ## 只重新部署（用上次的 .build 产物）
	@$(PY) scripts/build.py --skip-build

clean:  ## 删除 .build / .cache / __pycache__
	@$(PY) -c "import pathlib,shutil;[shutil.rmtree(p, ignore_errors=True) for p in ('.build','.cache')];[shutil.rmtree(p, ignore_errors=True) for root in ('src','tests','scripts','packaging') for p in pathlib.Path(root).rglob('__pycache__')]"

distclean: clean  ## clean + 清空 app/（保留 app/.dshlauncher 数据）
	@$(PY) -c "import pathlib,shutil;app=pathlib.Path('app');[shutil.rmtree(p) if p.is_dir() else p.unlink() for p in (app.iterdir() if app.is_dir() else []) if p.name != '.dshlauncher']"
