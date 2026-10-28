#!/usr/bin/env bash
# Kindle 桥 —— macOS / Linux 启动脚本
#
# 用法：
#   ./start.sh                             默认 8765 / 127.0.0.1 / 无头(headless)自动禁用浏览器
#   ./start.sh 9000                        指定端口（位置参数，兼容旧用法）
#   ./start.sh --port 9000 --host 0.0.0.0  显式指定端口与绑定地址
#   ./start.sh --browser                   强制打开浏览器（本机桌面用）
#   ./start.sh --no-browser                强制不打开浏览器（服务器 / SSH 用，也是默认）
#   ./start.sh --help                      查看帮助
set -euo pipefail

cd "$(dirname "$0")"

PORT=""
HOST="127.0.0.1"
BROWSER_FLAG=""   # ""=自动判断; "--no-browser" 或 "--browser"

# ---------- 解析参数 ----------
while [ $# -gt 0 ]; do
  case "$1" in
    --port)        PORT="${2:-}"; shift 2 ;;
    --port=*)      PORT="${1#*=}"; shift ;;
    --host)        HOST="${2:-}"; shift 2 ;;
    --host=*)      HOST="${1#*=}"; shift ;;
    --no-browser)  BROWSER_FLAG="--no-browser"; shift ;;
    --browser)     BROWSER_FLAG="--browser"; shift ;;
    -h|--help)     echo "用法: ./start.sh [--port N] [--host H] [--browser|--no-browser] [端口]"; exit 0 ;;
    ''|*[!0-9]*)   echo "[错误] 无法识别的参数: $1"; exit 1 ;;
    *)             PORT="$1"; shift ;;   # 位置参数 => 端口（兼容旧用法）
  esac
done
PORT="${PORT:-8765}"

# ---------- 无头自动判断 ----------
# 没有图形会话（DISPLAY 空）或处在 SSH 会话里时，默认不开浏览器，避免无谓报错。
if [ -z "$BROWSER_FLAG" ]; then
  if [ -z "${DISPLAY:-}" ] || [ -n "${SSH_CONNECTION:-}" ]; then
    BROWSER_FLAG="--no-browser"
  fi
fi

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
if [ "$BROWSER_FLAG" = "--no-browser" ]; then
  echo "[3/3] 正在启动（无头模式，不打开浏览器） http://${HOST}:${PORT}/"
else
  echo "[3/3] 正在启动，浏览器会自动打开 http://${HOST}:${PORT}/"
fi
echo
echo "  停止服务：按 Ctrl+C"
echo
exec "$PYEXE" app.py --port "$PORT" --host "$HOST" $BROWSER_FLAG
