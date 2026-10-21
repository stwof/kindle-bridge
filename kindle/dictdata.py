# -*- coding: utf-8 -*-
"""阅读器内嵌字典查询 —— 离线优先，可选挂载 CC-CEDICT StarDict。

设计目标（与「阅读器要流畅」强相关）：
  · 查询本身纯内存、O(1) 哈希查找，**不**做任何阻塞式联网；
  · 数据懒加载、进程内缓存，首次查询后才建索引，之后每次查询瞬时；
  · 前端用同一个词做缓存，重复查词不重复打后端。

数据分层：
  1. 内置离线词表 data/quickdict.json（随包发布，零网络，立即可用，覆盖常用中英词汇）。
  2. 若用户跑过 kindle/dictbuild.py 生成了 CC-CEDICT 的 StarDict（简体/繁體），
     则一并加载，获得近十万条中文词头的完整释义。

查询对大小写、首尾标点不敏感；中文按整词匹配，英文回退小写。
"""
from __future__ import annotations

import json
import os
import re
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
_QUICK_PATH = os.path.join(HERE, "data", "quickdict.json")

# 进程内缓存（只建一次）
_cache: dict = {"quick": None, "stardict": None, "ready": False, "note": ""}


def _load_quick() -> dict:
    try:
        with open(_QUICK_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _scan_stardict() -> dict:
    """找仓库根目录下「字典/」里的 StarDict 三件套（.ifo/.idx/.dict）。"""
    root = os.path.dirname(HERE)
    droot = os.path.join(root, "字典")
    out: dict = {}
    if not os.path.isdir(droot):
        return out
    for sub in sorted(os.listdir(droot)):
        folder = os.path.join(droot, sub)
        if not os.path.isdir(folder):
            continue
        ifos = [f for f in os.listdir(folder) if f.lower().endswith(".ifo")]
        if not ifos:
            continue
        base = os.path.splitext(ifos[0])[0]
        idx = os.path.join(folder, base + ".idx")
        dic = os.path.join(folder, base + ".dict")
        if os.path.isfile(idx) and os.path.isfile(dic):
            out[sub] = (idx, dic)
    return out


def _read_def(defpath: str, offset: int, length: int) -> str:
    with open(defpath, "rb") as f:
        f.seek(offset)
        return f.read(length).decode("utf-8", "replace")


def _build_index() -> None:
    quick = _load_quick()
    stardict: dict = {}
    found = _scan_stardict()
    note_parts = []
    for name, (idxp, dicp) in found.items():
        index: dict = {}
        try:
            with open(idxp, "rb") as f:
                data = f.read()
        except Exception:
            continue
        # StarDict .idx： 词头\0 + offset(4 字节大端) + length(4 字节大端)，按词头排序
        i, n = 0, len(data)
        while i < n:
            j = data.find(b"\x00", i)
            if j < 0:
                break
            word = data[i:j].decode("utf-8", "replace")
            if j + 9 <= n:
                offset, length = struct.unpack(">II", data[j + 1:j + 9])
                index[word] = (dicp, offset, length)
            i = j + 9
        stardict[name] = index
        note_parts.append(f"{name}({len(index)})")
    _cache["quick"] = quick
    _cache["stardict"] = stardict
    _cache["note"] = ("挂载 CC-CEDICT：" + "，".join(note_parts)) if note_parts else ""
    _cache["ready"] = True


def _ensure() -> dict:
    if not _cache["ready"]:
        _build_index()
    return _cache


_WS_RE = re.compile(r"^[\s\W]+|[\s\W]+$", re.UNICODE)


def _clean(word: str) -> str:
    w = (word or "").strip()
    # 去掉首尾空白与标点（中英文标点都去），避免「你好。」查不到「你好」
    w = _WS_RE.sub("", w)
    return w


def lookup(word: str) -> dict:
    """返回 {'found': bool, 'word': str, 'entries': [str, ...], 'note': str}。

    entries 每个元素是一条释义（已去掉空串）；中文条目首条通常带拼音 [pinyin]。
    """
    w = _clean(word)
    if not w:
        return {"found": False, "word": "", "entries": [], "note": ""}
    c = _ensure()
    entries: list = []
    seen = set()

    def add(text: str) -> None:
        for part in text.split("/"):
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                entries.append(part)

    # 1) 内置离线词表（大小写不敏感尝试）
    for key in dict.fromkeys([w, w.lower(), w.upper()]):
        if key in c["quick"]:
            add(c["quick"][key])

    # 2) CC-CEDICT StarDict（简繁），整词优先，再试小写
    if not entries:
        for _name, index in c["stardict"].items():
            for key in dict.fromkeys([w, w.lower(), w.upper()]):
                if key in index:
                    dicp, off, ln = index[key]
                    add(_read_def(dicp, off, ln))
                    break

    # 3) 英文短语：整句没查到时，退回最后一个单词
    if not entries and " " in w:
        last = _clean(w.split(" ")[-1])
        if last and last != w:
            return lookup(last)

    return {"found": bool(entries), "word": w, "entries": entries, "note": c["note"]}
