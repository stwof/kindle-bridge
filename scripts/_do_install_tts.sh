set -e
export HTTP_PROXY=http://127.0.0.1:61668
export HTTPS_PROXY=http://127.0.0.1:61668
export HF_ENDPOINT=https://hf-mirror.com
cd /d/WorkBuddy/kindle-bridge
echo "[1/4] upgrade pip"; .venv/Scripts/python.exe -m pip install --upgrade pip setuptools wheel
echo "[2/4] torch CPU (the big one)"; .venv/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
echo "[3/4] core reqs"; .venv/Scripts/python.exe -m pip install -r requirements.txt
echo "[4/4] Coqui TTS"; .venv/Scripts/python.exe -m pip install -r requirements-tts.txt
echo "=== INSTALL DONE ==="
.venv/Scripts/python.exe -c "import TTS, torch; print('TTS', TTS.__version__, '| torch', torch.__version__)"
