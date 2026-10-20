#!/usr/bin/env bash
# Kindle 桥 —— macOS / Linux 启动脚本
# 用法：  ./start.sh          启动（默认 8765 端口）
#         ./start.sh 9000     指定端口
set -euo pipefail

cd "$(dirname "$0")"
PORT="${1:-8765}"

echo
echo "  =========================================="
echo "    Kindle 桥 · 把 Kindle 的书与笔记搬到本地"
echo "  =========================================="
echo

# ---------- 1. 找一个能用的 Python ----------
PYEXE=""
if [ -x "./.venv/bin/python" ]; then
  PYEXE="./.venv/bin/python"
  echo "[1/3] 使用项目自带虚拟环境 .venv"
elif command -v python3 >/dev/null 2>&1; then
  PYEXE="python3"
  echo "[1/3] 使用系统 python3"
elif command -v python >/dev/null 2>&1; then
  PYEXE="python"
  echo "[1/3] 使用系统 python"
else
  echo
  echo "  [错误] 没找到 Python 3。请先安装："
  echo "    macOS:  brew install python3   或  https://www.python.org/downloads/"
  echo "    Debian: sudo apt install python3 python3-venv"
  echo
  exit 1
fi

# ---------- 2. 检查依赖 ----------
if ! "$PYEXE" -c "import opencc" >/dev/null 2>&1; then
  echo "[2/3] 正在安装依赖 opencc-python-reimplemented ..."
  "$PYEXE" -m pip install -r requirements.txt --disable-pip-version-check || {
    echo
    echo "  [提示] 自动安装失败（可能是网络受限）。程序仍可运行，"
    echo "         但简繁转换会退回内置小词表，冷僻字可能转不全。"
    echo
  }
else
  echo "[2/3] 依赖已就绪"
fi

# ---------- 3. 启动 ----------
echo "[3/3] 正在启动，浏览器会自动打开 http://127.0.0.1:${PORT}/"
echo
echo "  停止服务：按 Ctrl+C"
echo
exec "$PYEXE" app.py --port "$PORT"
