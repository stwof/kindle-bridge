# -*- coding: utf-8 -*-
"""扫描 Kindle 书库：书籍文件、格式、DRM 情况、最近阅读时间。"""
from __future__ import annotations

import json
import os
import re
import struct
from datetime import datetime

from .clippings import strip_series
from .device import read_text

EBOOK_EXT = {
    "azw", "azw3", "kfx", "mobi", "prc", "pdf", "txt", "epub",
    "doc", "docx", "rtf", "djvu", "fb2", "cbz", "htmlz",
}

# 微信读书「传书到手机」支持的格式
WECHAT_SUPPORTED = {"txt", "pdf", "epub", "doc", "docx", "mobi", "azw3"}

# 微信读书里体验较好的格式（可标注 / 目录 / 听书）
WECHAT_BEST = {"azw3", "mobi", "epub", "txt", "doc", "docx"}

ASIN_RE = re.compile(r"_(B0[A-Z0-9]{8}|[A-Z0-9]{10})$")

# documents 里不是书、不该列进书库的文件
SKIP_STEMS = {"my clippings", "kindle_users_guide", "user_guide"}


def _fmt_time(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def _stem(name: str) -> str:
    return os.path.splitext(name)[0]


def _extract_asin(stem: str) -> str:
    m = ASIN_RE.search(stem)
    return m.group(1) if m else ""


def clean_title(stem: str) -> str:
    t = ASIN_RE.sub("", stem).strip()
    return strip_series(t) or stem


def load_calibre_metadata(root: str) -> dict:
    """读取 driveinfo/metadata.calibre，返回 {文件名主干: {title, author}}。"""
    path = os.path.join(root, "metadata.calibre")
    if not os.path.isfile(path):
        return {}
    try:
        data = json.loads(read_text(path) or "[]")
    except (ValueError, TypeError):
        return {}
    if isinstance(data, dict):
        data = data.get("books", [])

    out = {}
    for b in data or []:
        lpath = b.get("lpath") or ""
        base = os.path.basename(lpath)
        if not base:
            continue
        authors = b.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        out[_stem(base)] = {
            "title": b.get("title") or clean_title(_stem(base)),
            "author": "、".join(a.strip() for a in authors if a and a.strip()),
        }
    return out


def detect_drm(path: str, ext: str) -> str:
    """尽力判断文件是否带 DRM：'clean' / 'drm' / 'unknown'。"""
    try:
        size = os.path.getsize(path)
        if size < 512:
            return "unknown"
        if ext in ("azw", "azw3", "mobi", "prc"):
            with open(path, "rb") as f:
                header = f.read(78)
                if len(header) < 78:
                    return "unknown"
                num_records = struct.unpack(">H", header[76:78])[0]
                if num_records < 1:
                    return "unknown"
                rec0 = struct.unpack(">I", f.read(4)[:4])[0]
                f.seek(rec0)
                r0 = f.read(512)
            if len(r0) < 200:
                return "unknown"
            base = r0.find(b"MOBI")
            if base < 0:
                return "unknown"
            if base + 0xA4 > len(r0):
                return "unknown"
            drm_offset = struct.unpack(">I", r0[base + 0x98: base + 0x9C])[0]
            drm_count = struct.unpack(">I", r0[base + 0x9C: base + 0xA0])[0]
            if drm_offset == 0xFFFFFFFF or drm_count == 0:
                return "clean"
            return "drm"
        if ext == "kfx":
            with open(path, "rb") as f:
                blob = f.read(4 * 1024 * 1024)
            if b"DRMION" in blob or b"drmion" in blob:
                return "drm"
            return "unknown"
        if ext == "pdf":
            with open(path, "rb") as f:
                blob = f.read(2 * 1024 * 1024)
            if b"/Encrypt" in blob:
                return "drm"
            return "clean"
    except OSError:
        return "unknown"
    return "clean"


def _wechat_note(ext: str, drm: str) -> tuple[bool, str]:
    if ext not in WECHAT_SUPPORTED:
        return False, f"微信读书不支持 .{ext}"
    if drm == "drm":
        return False, "含 DRM，无法转换/导入"
    if ext == "pdf":
        return True, "可导入，但 PDF 不可标注、体验一般"
    if ext in WECHAT_BEST:
        return True, "可直接导入，体验最佳"
    return True, "可直接导入"


def scan_library(device) -> dict:
    """扫描 documents 目录，返回 {books:[...], orphans:[...]}。"""
    docs = device.documents
    if not os.path.isdir(docs):
        return {"books": [], "orphans": []}

    meta = load_calibre_metadata(device.root)
    books = []
    sdr_dirs = {}

    try:
        entries = list(os.scandir(docs))
    except OSError:
        return {"books": [], "orphans": []}

    for e in entries:
        if e.is_dir() and e.name.lower().endswith(".sdr"):
            sdr_dirs[_stem(e.name)] = e
            continue

        if not e.is_file():
            continue
        stem, ext = os.path.splitext(e.name)
        ext = ext.lower().lstrip(".")
        if ext not in EBOOK_EXT:
            continue
        if stem.strip().lower() in SKIP_STEMS:
            continue

        st = e.stat()
        last_read = ""
        sdr = sdr_dirs.get(stem) or (
            os.path.join(docs, stem + ".sdr")
            if os.path.isdir(os.path.join(docs, stem + ".sdr")) else None
        )
        if sdr is not None:
            try:
                p = sdr.path if hasattr(sdr, "path") else sdr
                last_read = _fmt_time(os.path.getmtime(p))
            except OSError:
                pass

        info = meta.get(stem, {})
        author = info.get("author", "").strip()
        if author.lower() in ("未知", "unknown", "n/a") or "@" in author:
            author = ""
        drm = detect_drm(e.path, ext)
        ready, note = _wechat_note(ext, drm)

        books.append({
            "file": e.name,
            "path": e.path,
            "stem": stem,
            "title": strip_series(info.get("title") or clean_title(stem)),
            "author": author,
            "asin": _extract_asin(stem),
            "ext": ext,
            "size": st.st_size,
            "modified": _fmt_time(st.st_mtime),
            "last_read": last_read,
            "drm": drm,
            "wechat_ready": ready,
            "wechat_note": note,
            "convertible": drm != "drm",
        })

    books.sort(key=lambda b: (b["last_read"] or b["modified"]), reverse=True)

    matched = {b["stem"] for b in books}
    orphans = []
    for stem, d in sdr_dirs.items():
        if stem in matched:
            continue
        try:
            orphans.append({
                "stem": stem,
                "title": clean_title(stem),
                "last_read": _fmt_time(os.path.getmtime(d.path)),
            })
        except OSError:
            pass
    orphans.sort(key=lambda o: o["last_read"], reverse=True)

    return {"books": books, "orphans": orphans}
