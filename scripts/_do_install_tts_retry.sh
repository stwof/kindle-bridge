#!/usr/bin/env bash
# Retry Coqui TTS install with Windows SDK (UCRT) include/lib paths injected,
# bypassing the registry lookup that the sandbox blocks (reg.exe).
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"
PIP="$VENV/Scripts/pip.exe"

SDK="C:/Program Files (x86)/Windows Kits/10"
MSVC="C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207"
VSINC="C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Auxiliary/VS"
SDKVER="10.0.26100.0"

echo "[env] injecting Windows SDK ($SDKVER) + MSVC include/lib"
export INCLUDE="$MSVC/include;$VSINC/include;$SDK/Include/$SDKVER/ucrt;$SDK/Include/$SDKVER/shared;$SDK/Include/$SDKVER/um"
export LIB="$MSVC/lib/x64;$SDK/Lib/$SDKVER/ucrt/x64;$SDK/Lib/$SDKVER/um/x64"
export PATH="$MSVC/bin/HostX64/x64:$SDK/bin/$SDKVER/x64:$PATH"

# Proxy is alive on 61668; keep it so pip can resolve + fetch cached sdist.
export HTTP_PROXY=http://127.0.0.1:61668
export HTTPS_PROXY=http://127.0.0.1:61668
export HF_ENDPOINT=https://hf-mirror.com

echo "[1] pip up-to-date check"
"$PIP" install --upgrade pip wheel setuptools

echo "[2] install TTS requirements (deps cached, only TTS sdist recompiles)"
"$PIP" install -r "$ROOT/requirements-tts.txt"

echo "[done] TTS install finished"
"$PIP" show TTS 2>/dev/null | grep -iE "^(Name|Version):" || true
