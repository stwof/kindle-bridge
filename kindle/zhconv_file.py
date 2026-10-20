# -*- coding: utf-8 -*-
"""文件级简繁转换：EPUB 与纯文本 TXT。

为什么单独一个模块：EPUB 是 zip 容器（要进 epub.py 逐文件改文本节点），
TXT 是裸文本（要猜编码再整体转）。两者入口不同，但对外统一成
`zhconv_file(src, dst, to)` 一个函数，前端只管调它。

to 取值：'auto'（默认，自动判别当前字体再转成另一边）/ 'simplified' / 'traditional'。
"""
from __future__ import annotations

import os

from . import epub, hanzi

_TXT_EXT = (".txt", ".text", ".md", ".csv")
_EPUB_EXT = (".epub",)


def _sniff_encoding(blob: bytes) -> str:
    """猜一份文本的编码。优先 UTF-8（含 BOM），再试 GB18030（简体 Windows 最常见），
    再试 Big5（繁体 Windows），最后退回 latin-1（永不失败，但乱码时就是乱码）。
    """
    if blob.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # 纯 UTF-8 自洽检测
    try:
        blob.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    for enc in ("gb18030", "big5"):
        try:
            blob.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def _convert_txt(src: str, dst: str, to: str) -> dict:
    with open(src, "rb") as f:
        blob = f.read()
    enc = _sniff_encoding(blob)
    text = blob.decode(enc, errors="replace")

    if not hanzi.looks_chinese(text):
        return {"ok": True, "out": src, "skipped": True,
                "reason": "没有检测到中文，原样不动", "encoding": enc}

    new = hanzi.convert(text, to)
    direction = "繁体" if (to in ("traditional", "繁体", "trad")) else (
        "简体" if to in ("simplified", "简体", "simp") else "自动")

    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(new)

    changed = new != text
    return {"ok": True, "out": dst, "direction": direction,
            "encoding": enc, "changed": changed,
            "bytes_before": len(blob), "bytes_after": len(new.encode("utf-8"))}


def zhconv_file(src: str, dst: str, to: str = "auto") -> dict:
    """统一入口：按扩展名派发到 EPUB 或 TXT 转换器。

    返回 dict：ok / out / direction / 各格式特有字段 / changed。
    出错时返回 {"ok": False, "error": ...}。
    """
    if not os.path.isfile(src):
        return {"ok": False, "error": f"源文件不存在：{src}"}
    if os.path.abspath(src) == os.path.abspath(dst):
        return {"ok": False, "error": "源文件与目标文件不能相同"}
    if not hanzi.available():
        return {"ok": False, "error": "简繁数据表缺失，无法转换"}

    low = src.lower()
    try:
        if low.endswith(_EPUB_EXT):
            return epub.convert_epub(src, dst, to)
        if low.endswith(_TXT_EXT):
            return _convert_txt(src, dst, to)
    except Exception as ex:  # 转换中任何意外都不该让服务崩，记下来返回
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
    return {"ok": False, "error": f"不支持的格式（仅 EPUB / TXT）：{os.path.basename(src)}"}
