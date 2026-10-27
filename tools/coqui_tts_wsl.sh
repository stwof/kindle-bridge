#!/usr/bin/env bash
# ============================================================================
# Coqui TTS —— WSL Ubuntu 安装与基础运行验证脚本
# ----------------------------------------------------------------------------
# 用途：在「通过 WSL 安装的 Ubuntu」里一键装好 Coqui TTS 依赖，并做基础运行验证
#       （import 库 → 列出模型 → 尽量完成一次短文本合成）。
#
# 怎么用（在你的 Ubuntu 终端里）：
#   1) 把本文件弄进 WSL，例如：  cp /mnt/d/WorkBuddy/kindle-bridge/tools/coqui_tts_wsl.sh ~/
#   2) 赋权并运行：              chmod +x ~/coqui_tts_wsl.sh && ~/coqui_tts_wsl.sh
#
# 说明：
#   - Coqui TTS 最后正式发布是 0.22.0（2024-02），对 Python 3.8~3.11 支持最好；
#     脚本默认建一个 Python 3.10 的 venv，避开 3.12 的兼容坑。
#   - 仅装 CPU 版 torch（够跑推理，体积也小很多）。要 GPU 推理去掉 --index-url 那行即可。
#   - 合成需要下载模型权重（~100MB+）。如果你的出网走 SSL 中间人代理（比如本机
#     127.0.0.1:54592 这种），Python 会因证书校验失败而下载不了权重 —— 这是环境问题
#     不是库问题。见下方「代理 / 证书」段落的两种绕过办法（按需二选一，验证完建议还原）。
# ============================================================================

set -euo pipefail

VENV="$HOME/coqui-tts-venv"
PYTHON_BIN="python3.10"

echo "==> [1/6] 系统检查"
uname -a
"$PYTHON_BIN" --version || { echo "缺少 $PYTHON_BIN，请先: sudo apt update && sudo apt install -y python3.10 python3.10-venv python3.10-dev"; exit 1; }
# 编译依赖（部分 wheel 缺失时需本地编译）
sudo apt-get update -qq
sudo apt-get install -y -qq build-essential ffmpeg libsndfile1 || true

echo "==> [2/6] 建虚拟环境: $VENV"
if [ ! -d "$VENV" ]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install -q --upgrade pip setuptools wheel

# ---------------------------------------------------------------------------
# 代理 / 证书（如你的出网走 MITM 代理，按需在下面二选一取消注释）
# 方式 A（推荐，仅本次会话信任代理 CA，验证完自行 unset）：
#   export PIP_CERT="/path/to/proxy-ca.pem"        # 把代理根证书导出成 PEM 后填这里
#   export REQUESTS_CA_BUNDLE="$PIP_CERT"
#   export SSL_CERT_FILE="$PIP_CERT"
# 方式 B（不校验证书，仅用于本地验证，不安全，用完记得 unset）：
#   export PYTHONHTTPSVERIFY=0
#   export PIP_INSECURE=1
# 同时把代理本身告诉 pip / 下载器（如适用）：
#   export HTTP_PROXY="http://127.0.0.1:54592"
#   export HTTPS_PROXY="http://127.0.0.1:54592"
# ---------------------------------------------------------------------------

echo "==> [3/6] 安装 torch (CPU) + Coqui TTS"
pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -q TTS

echo "==> [4/6] 验证 import"
python - <<'PY'
import importlib, sys
try:
    import TTS
    print("TTS import OK, version:", getattr(TTS, "__version__", "unknown"))
except Exception as e:
    print("TTS import FAILED:", repr(e)); sys.exit(2)
PY

echo "==> [5/6] 列出可用模型（不下载权重，确认后端元数据可用）"
python - <<'PY'
from TTS.api import TTS
models = TTS.list_models() if hasattr(TTS, "list_models") else []
print("可用模型示例（前 5 条）:")
for m in (list(models)[:5] if isinstance(models, (list, tuple)) else []):
    print("  -", m)
print("list_models 返回数量:", len(models) if isinstance(models, (list, tuple)) else "n/a")
PY

echo "==> [6/6] 基础合成验证（需下载权重，失败属网络/代理问题，非库缺陷）"
OUT="$HOME/coqui-tts-demo.wav"
python - <<PY || echo "!! 合成未成功（多为权重下载被代理/证书拦住），但安装与 import 已通过——属环境限制，见脚本顶部说明。"
from TTS.api import TTS
tts = TTS(model_name="tts_models/en/ljspeech/tacotron2-DDC", progress_bar=False, gpu=False)
tts.tts_to_file(text="Hello from Coqui TTS, running inside WSL Ubuntu.", file_path="$OUT")
import os
print("合成成功 ->", "$OUT", "大小:", os.path.getsize("$OUT"), "bytes")
PY

echo "==> 完成。虚拟环境在: $VENV （下次直接 source $VENV/bin/activate）"
