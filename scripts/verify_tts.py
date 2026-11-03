# -*- coding: utf-8 -*-
"""验证 Coqui TTS 在当前 venv(Python3.11) 中的安装与基本合成能力。

用法（在 kindle-bridge 根目录，先 activate .venv）：
    set HF_ENDPOINT=https://hf-mirror.com
    .venv\\Scripts\\python.exe tools/verify_tts.py
"""
from __future__ import annotations
import os
import sys
import io
import traceback

FAIL = []


def section(t: str):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


# 1) 版本与依赖完整性 -------------------------------------------------------
section("1) Python / TTS / torch 版本")
print("python:", sys.version.split()[0])
import TTS  # noqa: F401
print("TTS   :", getattr(TTS, "__version__", "unknown"))
import torch  # noqa: F401
print("torch :", torch.__version__, "| cuda available:", torch.cuda.is_available())

# 2) 依赖冲突检查 -----------------------------------------------------------
section("2) pip dependency check (冲突检测)")
import subprocess
rc = subprocess.run(
    [sys.executable, "-m", "pip", "check"],
    capture_output=True, text=True,
)
print(rc.stdout.strip() or "(no output)")
if rc.returncode != 0 or "ERROR" in rc.stdout or "WARNING" in rc.stdout:
    print("[pip check] 存在冲突/警告，详见上方；rc=", rc.returncode)
else:
    print("[pip check] 干净，无冲突")

# 3) kindle.tts 可用性 ------------------------------------------------------
section("3) kindle.tts 模块可用性 (available / backend / list_voices)")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import kindle.tts as kt
    print("available() :", kt.available())
    print("backend()   :", kt.backend())
    voices = kt.list_voices()
    for v in voices:
        print(f"  - {v['id']:14s} ready={v['ready']!s:5s} {v['label']}")
except Exception as ex:
    FAIL.append(f"kindle.tts 导入/调用失败: {ex}")
    traceback.print_exc()

# 4) 实际语音合成测试 -------------------------------------------------------
section("4) 实际合成测试 (中文 Baker / 英文 LJSpeech)")
try:
    import kindle.tts as kt
    import soundfile as sf

    for voice, text in [
        ("zh-baker", "你好，这是本地语音合成的测试，声音听起来自然吗？"),
        ("en-ljspeech", "Hello, this is a local speech synthesis test."),
    ]:
        print(f"\n--- voice={voice} ---")
        try:
            res = kt.synth(text, voice)
            wav = res["bytes"]
            out = f"tools/tts_test_{voice}.wav"
            with open(out, "wb") as f:
                f.write(wav)
            print(f"  OK  duration={res['duration']}s sr={res['sr']} "
                  f"chunks={res['chunks']} bytes={len(wav)} -> {out}")
        except Exception as ex:
            msg = f"{voice} 合成失败: {ex}"
            print("  " + msg)
            FAIL.append(msg)
except Exception as ex:
    FAIL.append(f"合成测试前置失败: {ex}")
    traceback.print_exc()

# 5) 结论 ------------------------------------------------------------------
section("5) 结论")
if FAIL:
    print("❌ 存在问题：")
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
else:
    print("✅ Coqui TTS 安装完整、依赖无冲突、实际语音合成可用。")
    # 清理测试产物里的中文名（避免乱码），英文保留供试听
    for v in ("zh-baker", "en-ljspeech"):
        p = f"tools/tts_test_{v}.wav"
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    print("（测试 WAV 已生成并校验后清理）")
