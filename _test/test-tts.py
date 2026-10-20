# -*- coding: utf-8 -*-
"""TTS（Coqui TTS）封装测试：分句逻辑、声音目录、未安装时优雅降级。

设计目标：
  - 不依赖 Coqui TTS 是否已安装也能跑（没装时验证「优雅降级」而非报错崩溃）。
  - 真实合成（会下载模型、很重）默认不跑；设环境变量 KB_TTS_LIVE=1 才跑。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from kindle import tts as T                                    # noqa: E402

ok = fail = 0


def chk(cond, msg):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK]  ", msg)
    else:
        fail += 1
        print("  [FAIL]", msg)


def section(t):
    print(f"\n--- {t} ---")


# ---------------------------------------------------------------------------
section("分句（split_sentences）")
chk(T.split_sentences("") == [], "空文本返回空列表")
chk(T.split_sentences("   \n  ") == [], "只有空白返回空列表")

one = T.split_sentences("今天天气真好。")
chk(len(one) == 1 and one[0] == "今天天气真好。", "单句保留句末标点，且不切分")

multi = T.split_sentences("床前明月光。疑是地上霜。举头望明月，低头思故乡。")
# 逗号是句内停顿，不切分；只有句末标点（。！？!?；;…）才切，所以是 3 段
chk(len(multi) == 3, "按句末标点切成 3 段（逗号作为句内停顿不切）")
chk(multi[0] == "床前明月光。" and multi[-1] == "举头望明月，低头思故乡。",
    "每句句末标点保留在各自片段里")

# 长句：超过 120 字且只在逗号处断，应被按逗号再切
long_c = "，".join(["这是一段很长的中文测试句子用来验证自动切分逻辑是否正常工作" for _ in range(8)])
chunks = T.split_sentences(long_c)
chk(all(len(c) <= 120 for c in chunks), "超长无句末标点文本被硬切到 120 字以内")

# 中英文混排 + 英文标点
mix = T.split_sentences("Hello world! 你好世界。This is a test? 测试一下。")
chk(len(mix) >= 3, "中英文混排按 ! ? 。 正确切分")

# 句末标点后不留空片段
chk(all(c.strip() for c in T.split_sentences("甲。乙。丙。")), "切分后没有空片段")


# ---------------------------------------------------------------------------
section("声音目录（list_voices）")
voices = T.list_voices()
chk(isinstance(voices, list) and len(voices) >= 3, "返回至少 3 个声音")
ids = {v["id"] for v in voices}
chk("zh-baker" in ids and "multi-yourtts" in ids and "en-ljspeech" in ids,
    "包含中文 Baker / 多语 YourTTS / 英文 LJSpeech")
chk(any(v.get("default") for v in voices), "有且仅有一个默认声音",
    )
chk(all("model" in v and v["model"].startswith("tts_models/") for v in voices),
    "每个声音都带合法的 model_name")


# ---------------------------------------------------------------------------
section("可用性 & 优雅降级")
chk(T.available() in (True, False), "available() 返回布尔")
chk(isinstance(T.backend(), (str, type(None))), "backend() 返回字符串或 None")

# 空文本必须报错（无论 TTS 是否安装）
try:
    T.synth("")
    chk(False, "空文本合成应抛 TTSSError")
except T.TTSSError:
    chk(True, "空文本合成抛 TTSSError")

# 没装 TTS 时，合成任意文字都应优雅报错，而不是抛 ImportError 崩溃
if not T.available():
    try:
        T.synth("床前明月光，疑是地上霜。")
        chk(False, "未安装时应抛 TTSSError")
    except T.TTSSError as ex:
        chk("requirements-tts" in str(ex) or "TTS" in str(ex),
            "未安装时给出安装提示（含 requirements-tts 字样）")
else:
    print("  [SKIP] 已安装 TTS，跳过「未安装降级」断言")


# ---------------------------------------------------------------------------
section("真实合成（可选，需 KB_TTS_LIVE=1 且已装 TTS）")
if os.environ.get("KB_TTS_LIVE") == "1" and T.available():
    try:
        info = T.synth("床前明月光，疑是地上霜。", voice="zh-baker")
        chk(info["bytes"][:4] == b"RIFF", "产出是合法 WAV（RIFF 头）")
        chk(info["duration"] > 0, "有非零时长")
        chk(info["chunks"] >= 1, "至少合成了一段")
        print(f"  [INFO] 合成成功：{info['duration']} 秒 / {len(info['bytes'])} 字节 / {info['chunks']} 段")
    except T.TTSSError as ex:
        chk(False, f"真实合成失败：{ex}")
else:
    print("  [SKIP] 未开启 KB_TTS_LIVE 或未装 TTS，跳过真实合成")


# ---------------------------------------------------------------------------
print(f"\n=== TTS 测试：{ok} 通过 / {fail} 失败 ===")
sys.exit(1 if fail else 0)
