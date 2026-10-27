# -*- coding: utf-8 -*-
"""本地语音合成（TTS）—— 基于 Coqui TTS 开源引擎。

为什么用 Coqui TTS：
  - 完全离线：模型下载到本机后，合成不再联网、不上传任何文字。
  - 开源：引擎是 Mozilla Public License 2.0（见 THIRD_PARTY_NOTICES.md）。
  - 中文有官方模型（Baker / Tacotron2），也支持多语 YourTTS、英文 LJSpeech。

设计要点：
  - **惰性导入**：TTS 依赖 PyTorch，很重。本模块在「真正要合成」时才 import，
    所以没装 TTS 时，整个 Kindle 桥照常启动、照常跑其它功能。
  - **优雅降级**：`available()` 在没装 TTS 时返回 False；`synth()` 抛 `TTSSError`，
    调用方据此给前端返回清晰的安装提示，而不是崩。
  - **模型按需下载 + 缓存**：首次用某个声音会触发 Coqui 自动下载（约 50~120 MB），
    之后缓存在用户目录，不用再下。模型不在仓库里分发。
  - **长文本分句**：Coqui 的单次合成有长度上限，容易截断。这里按中英文句读切分，
    逐句合成后用短静音拼接，既能读长段落，又保留自然停顿。
"""
from __future__ import annotations

import io
import os
import re

# ---------------------------------------------------------------------------
# 声音目录（精选、稳定的官方模型）
# ---------------------------------------------------------------------------
# key        → 前端下拉用的稳定标识
# label      → 中文展示名
# model      → Coqui 的 model_name（即下载路径）
# lang       → 展示用语言标签
# language   → 传给模型的语言码（多语模型必须给）
# note       → 额外说明（首次下载体量等）
_CATALOG: dict[str, dict] = {
    "zh-baker": {
        "label": "中文 · 标准女声（Baker / Tacotron2）",
        "model": "tts_models/zh-CN/baker/tacotron2-DDC-GST",
        "lang": "zh-CN",
        "note": "普通话女声，单说话人，约 50 MB",
    },
    "zh-baker-dca": {
        "label": "中文 · 清晰女声（Baker / Tacotron2-DCA）",
        "model": "tts_models/zh-CN/baker/tacotron2-DCA",
        "lang": "zh-CN",
        "note": "普通话女声变体，约 50 MB",
    },
    "multi-yourtts": {
        "label": "多语 · YourTTS（含中文，可换说话人）",
        "model": "tts_models/multilingual/multi-dataset/your_tts",
        "lang": "多语（含中文）",
        "language": "zh-cn",
        "note": "多说话人、多语言；中文用 zh-cn，约 120 MB",
    },
    "en-ljspeech": {
        "label": "英文 · LJSpeech（女声）",
        "model": "tts_models/en/ljspeech/tacotron2-DDC",
        "lang": "en",
        "note": "英文女声，约 40 MB",
    },
}
DEFAULT_VOICE = "zh-baker"

# 单句最长字数：超过就按逗号/长度再切，避免 Coqui 截断或卡死
_CHUNK_LIMIT = 120
# 句间静音（秒），让朗读有自然停顿
_PAUSE_SEC = 0.12


class TTSSError(Exception):
    """合成相关的、可安全回传给前端的错误。"""


# ---------------------------------------------------------------------------
# 分句
# ---------------------------------------------------------------------------
# 句末标点（中英文混排都要照顾）：。！？!?；;… 以及换行
_SENT_SPLIT = re.compile(r"([。！？!?；;…\n]+)")
# 长句内部再切的分隔符
_INNER_SPLIT = re.compile(r"([，,、；;])")


def split_sentences(text: str) -> list[str]:
    """把一段文字切成适合逐句合成的短句。

    规则：
      1. 先按句末标点切（保留标点，贴合语义）；
      2. 仍超过 _CHUNK_LIMIT 的句子，按逗号/顿号再切；
      3. 完全没有标点的超长串，按字数硬切。
    返回非空片段列表。
    """
    if not text:
        return []

    parts = _SENT_SPLIT.split(text)
    chunks: list[str] = []
    buf = ""
    for i, seg in enumerate(parts):
        buf += seg
        # 奇数下标是「句末标点」，遇到就收一句
        if i % 2 == 1 and buf.strip():
            chunks.append(buf.strip())
            buf = ""
    if buf.strip():
        chunks.append(buf.strip())

    out: list[str] = []
    for c in chunks:
        out.extend(_split_long(c))
    return [c for c in out if c.strip()]


def _split_long(c: str, limit: int = _CHUNK_LIMIT) -> list[str]:
    if len(c) <= limit:
        return [c]
    pieces = _INNER_SPLIT.split(c)
    buf = ""
    res: list[str] = []
    for seg in pieces:
        buf += seg
        if len(buf) >= limit:
            res.append(buf)
            buf = ""
    if buf:
        res.append(buf)
    final: list[str] = []
    for r in res:
        if len(r) <= limit:
            final.append(r)
        else:
            for i in range(0, len(r), limit):
                final.append(r[i:i + limit])
    return final


# ---------------------------------------------------------------------------
# 可用性检测 / 元信息
# ---------------------------------------------------------------------------
def available() -> bool:
    """Coqui TTS 是否已安装（无需模型已下载，模型在首次合成时按需拉取）。"""
    try:
        import TTS  # noqa: F401
        return True
    except Exception:
        return False


def backend() -> str | None:
    """返回引擎标识，没装则返回 None。"""
    if not available():
        return None
    try:
        from TTS import __version__
        return "coqui-tts " + str(__version__)
    except Exception:
        return "coqui-tts"


def _model_cache_dir() -> str:
    """Coqui 默认把下载好的模型放在 ~/.local/share/tts。"""
    return os.path.join(os.path.expanduser("~"), ".local", "share", "tts")


def _model_ready(model_name: str) -> bool:
    """尽力判断某个模型是否已经下载到本地缓存（不触发下载）。"""
    try:
        name = model_name.replace("/", "--")
        return os.path.isdir(os.path.join(_model_cache_dir(), name))
    except Exception:
        return False


def list_voices() -> list[dict]:
    """返回声音目录，每条带 ready（是否已下载到本地）。"""
    out: list[dict] = []
    for key, v in _CATALOG.items():
        out.append({
            "id": key,
            "label": v["label"],
            "model": v["model"],
            "lang": v.get("lang", ""),
            "note": v.get("note", ""),
            "ready": _model_ready(v["model"]),
            "default": key == DEFAULT_VOICE,
        })
    return out


# ---------------------------------------------------------------------------
# 合成
# ---------------------------------------------------------------------------
_MODEL_CACHE: dict[str, object] = {}

# ---------------------------------------------------------------------------
# torch.load 兼容性补丁
# ---------------------------------------------------------------------------
# TTS 0.22 的检查点（含优化器状态）引用了 TTS 自定义类（如 RAdam）。
# PyTorch 2.6+ 把 torch.load 的默认 weights_only 改成 True，会拒绝反序列化这些类，
# 表现为「Weights only load failed ... GLOBAL TTS.utils.radam.RAdam was not an
# allowed global」。本地模型是官方可信、已缓存到本机的检查点，离线使用，这里在
# 加载模型前一次性把 torch.load 强制为 weights_only=False 以兼容 TTS 0.22。
_TORCH_PATCHED = False


def _patch_torch_for_tts() -> None:
    global _TORCH_PATCHED
    if _TORCH_PATCHED:
        return
    try:
        import torch

        _orig = torch.load

        def _load(f, *args, **kwargs):
            kwargs["weights_only"] = False
            return _orig(f, *args, **kwargs)

        torch.load = _load
        _TORCH_PATCHED = True
    except Exception:
        # 装了不兼容版本时静默失败，让后续真实报错暴露出来
        pass


def _get_model(model_name: str):
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]
    try:
        from TTS.api import TTS
    except Exception as ex:  # pragma: no cover - 没装时由 available() 挡在前面
        raise TTSSError("未安装 Coqui TTS，请先 pip install -r requirements-tts.txt 后重启服务") from ex
    _patch_torch_for_tts()  # 必须在构造 TTS() 加载检查点之前打补丁
    try:
        tts = TTS(model_name=model_name, progress_bar=False, gpu=False)
    except Exception as ex:
        raise TTSSError(f"加载语音模型失败：{ex}") from ex
    _MODEL_CACHE[model_name] = tts
    return tts


def synth(text: str, voice: str | None = None) -> dict:
    """把文字合成成语音，返回 WAV 字节与元信息。

    返回 dict: {bytes, sr, samples, duration, chunks, voice, model, speaker, language}
    未装 TTS 或文字为空时抛 TTSSError。
    """
    if not text or not text.strip():
        raise TTSSError("没有可朗读的文字")
    if not available():
        raise TTSSError("未安装 Coqui TTS，请先 pip install -r requirements-tts.txt 后重启服务")

    key = voice or DEFAULT_VOICE
    info = _CATALOG.get(key)
    if info is None:
        # 允许直接传 model_name 当声音标识
        model_name = key
        language = None
    else:
        model_name = info["model"]
        language = info.get("language")

    import numpy as np
    import soundfile as sf

    tts = _get_model(model_name)
    sr = 22050
    synthobj = getattr(tts, "synthesizer", None)
    if synthobj is not None:
        sr = int(getattr(synthobj, "output_sample_rate", 22050) or 22050)

    # 说话人 / 语言：只在模型支持时才传，否则 Coqui 会报错
    speaker = None
    if getattr(tts, "is_multi_speaker", False):
        spk = getattr(tts, "speakers", None)
        speaker = spk[0] if spk else None
    if getattr(tts, "is_multi_lingual", False) and not language:
        langs = getattr(tts, "languages", None)
        language = langs[0] if langs else None

    chunks = split_sentences(text)
    if not chunks:
        raise TTSSError("没有可朗读的文字")

    waves: list[np.ndarray] = []
    pause = np.zeros(int(sr * _PAUSE_SEC), dtype=np.float32)
    for ch in chunks:
        if not ch.strip():
            continue
        kw: dict = {}
        if speaker:
            kw["speaker"] = speaker
        if language:
            kw["language"] = language
        try:
            w = tts.tts(text=ch, **kw)
        except Exception as ex:
            raise TTSSError(f"合成失败（句：「{ch[:20]}…」）：{ex}") from ex
        waves.append(np.asarray(w, dtype=np.float32))
        waves.append(pause)

    if not waves:
        raise TTSSError("生成失败：文本为空或无法合成")

    full = np.concatenate(waves)
    buf = io.BytesIO()
    sf.write(buf, full, sr, format="WAV")
    body = buf.getvalue()

    return {
        "bytes": body,
        "sr": sr,
        "samples": int(len(full)),
        "duration": round(len(full) / sr, 2),
        "chunks": len([w for w in waves if len(w) != len(pause)]),
        "voice": key,
        "model": model_name,
        "speaker": speaker,
        "language": language,
    }
