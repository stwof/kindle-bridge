#!/usr/bin/env bash
# Kindle 桥 —— 后台启动器（WSL / 无 systemd 的 Linux / headless 服务器）
#
# 用法：
#   ./run.sh              # 默认监听 127.0.0.1:8765，日志写到 ~/kb.log
#   ./run.sh 9000        # 指定端口（位置参数，可选）
#
# 设计要点：
#   - 自动识别虚拟环境：优先 .venv，其次 venv（两者之一存在即可）
#   - 缺虚拟环境时给出明确报错，而不是静默失败
#   - 不自动开浏览器（headless 友好）
#   - 用 nohup/setsid 拉起后可脱离终端运行：  setsid ./run.sh &
#
# 注意：app.py 自带端口占用保护。若 8765 已被旧实例占用，新实例会拒绝启动
#       并打印提示——此时先 `pkill -f "app.py --host 127.0.0.1"` 结束旧进程再起。

set -u

# 切到脚本所在目录
cd "$(dirname "$0")" || exit 1

# 解析可选端口位置参数
PORT=8765
if [ $# -ge 1 ]; then
  case "$1" in
    ''|*[!0-9]*) echo "ERROR: 端口必须是数字，收到 '$1'" >&2; exit 1 ;;
    *) PORT="$1" ;;
  esac
fi

# 定位虚拟环境（兼容 .venv 与 venv 两种命名）
VENV_DIR=""
if [ -x .venv/bin/python ]; then
  VENV_DIR=".venv"
elif [ -x venv/bin/python ]; then
  VENV_DIR="venv"
fi

if [ -z "$VENV_DIR" ]; then
  echo "ERROR: 未找到虚拟环境（.venv 或 venv）。请先建好并装依赖：" >&2
  echo "    python3 -m venv .venv" >&2
  echo "    . .venv/bin/activate" >&2
  echo "    pip install -r requirements.txt" >&2
  echo "    # 可选（需 Python 3.9~3.11）：pip install -r requirements-tts.txt" >&2
  exit 1
fi

LOGFILE="$HOME/kb.log"
echo "使用虚拟环境: $VENV_DIR/  端口: $PORT  日志: $LOGFILE"

# 用 venv 里的 python 直接启动，日志追加到 kb.log
exec "$VENV_DIR/bin/python" app.py --port "$PORT" --host 127.0.0.1 --no-browser >> "$LOGFILE" 2>&1
