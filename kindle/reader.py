# -*- coding: utf-8 -*-
"""本地阅读器后端：书架、让任何一本书都能被前端渲染、阅读进度与标注。

为什么单独一个模块：
  - 前端渲染只用 epub.js，它只认 EPUB。而本机上的书有 EPUB / TXT / MOBI 家族三种，
    这里负责「把书变成能读的状态」：
        EPUB       → 直接用；
        TXT        → 现场打包成 EPUB（epub.build_epub），不依赖 Calibre；
        MOBI 家族  → 交给 Calibre 的 ebook-convert 转成 EPUB（转一次就缓存）。
  - 阅读进度、划线标注落在 `书架/` 两个 JSON 里（用户随时能打开看、能自己改）。
  - 全程本地，不联网；Calibre 是外调的独立进程，不引入它的代码。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

from . import convert as conv_mod
from . import device as dev_mod
from . import epub as epub_mod
from . import library as lib_mod
from . import mobi as mobi_mod
from . import paths as paths_mod
from . import zhconv_file as zcf_mod

EPUB_EXT = ".epub"
TXT_EXT = (".txt", ".text", ".md")
MOBI_EXT = (".mobi", ".azw", ".azw3", ".prc")
READABLE_EXT = (EPUB_EXT,) + TXT_EXT + MOBI_EXT

_DATA = paths_mod.data_dir()
SHELF_DIR = os.path.join(_DATA, "书架")
PROGRESS_PATH = os.path.join(SHELF_DIR, "进度.json")
ANNOT_PATH = os.path.join(SHELF_DIR, "标注.json")
_BOOKS_CACHE = os.path.join(_DATA, "工具", "缓存", "阅读器", "书籍")
_COVERS_CACHE = os.path.join(_DATA, "工具", "缓存", "阅读器", "封面")

_MAX_TEXT_BYTES = 4 * 1024 * 1024        # TXT 单本上限
_CHUNK_PARAS = 260                        # TXT 每章多少段（切太碎目录会很长）
_KEY_RE = re.compile(r"^[0-9a-f]{16}$")

_lock = threading.Lock()
_INDEX: dict[str, str] = {}               # key -> 绝对路径（见 resolve_path）


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def key_for(path: str) -> str:
    """用绝对路径派生一个稳定的 key（进度、标注都挂在这个 key 上）。"""
    norm = os.path.normcase(os.path.abspath(path))
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def _local(el) -> str:
    """XML 元素的本地名（去掉命名空间前缀），免去维护 NS 字典。"""
    return el.tag.split("}")[-1]


def _resolve_href(base_dir: str, href: str) -> str:
    href = href.split("#", 1)[0].split("?", 1)[0].replace("\\", "/")
    parts: list[str] = []
    for seg in (base_dir.split("/") if base_dir else []) + href.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def _fmt_time(ts) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


# ---------------------------------------------------------------------------
# 元信息
# ---------------------------------------------------------------------------
def _sniff_prefix(blob: bytes) -> str:
    """只读了前若干字节时猜编码。

    坑：8 KB 头很可能把一个多字节汉字切成两半，整个头就「不是合法 UTF-8」，
    于是被误判成 GB18030（它几乎能吃下任何字节串），书名因此变乱码。
    所以先容忍尾部少 1~3 字节再判 UTF-8，判不出才退回完整嗅探。
    """
    if blob.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for cut in (0, 1, 2, 3):
        head = blob[:len(blob) - cut] if cut else blob
        if not head:
            break
        try:
            head.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            continue
    return zcf_mod._sniff_encoding(blob)


def _title_author_from_text(text: str, filename: str) -> tuple[str, str]:
    """书名/作者：文件名兜底；首行若很短就当书名，再往后扫几行找「作者：」。"""
    title = os.path.splitext(filename)[0]
    author = ""
    seen = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if seen == 0 and len(s) <= 40:
            title = s
        m = re.search(r"作者[:：\s]*([^\s，,。;；]{1,30})", s)
        if m:
            author = m.group(1).strip("《》[]()")
            break
        seen += 1
        if seen >= 8:                       # 只看开头几行，别把正文里的人名当作者
            break
    return title, author


def _txt_meta(path: str) -> tuple[str, str]:
    try:
        with open(path, "rb") as f:
            blob = f.read(8192)
        text = blob.decode(_sniff_prefix(blob), errors="replace")
    except OSError:
        text = ""
    return _title_author_from_text(text, os.path.basename(path))


def meta(path: str) -> dict:
    """书名 / 作者 / 是否 DRM。任何异常都退化成「文件名当书名」，不抛。"""
    ext = os.path.splitext(path)[1].lower()
    out = {"title": "", "author": "", "drm": False}
    try:
        if ext == EPUB_EXT:
            rep = epub_mod.inspect_epub(path)
            out["title"] = rep.get("title") or ""
            out["author"] = rep.get("author") or ""
            out["drm"] = bool(rep.get("drm"))
        elif ext in MOBI_EXT:
            rep = mobi_mod.inspect_mobi(path)
            out["title"] = rep.get("title") or ""
            out["author"] = rep.get("author") or ""
            drm = rep.get("drm")
            out["drm"] = bool(drm) and str(drm) not in ("无", "")
        elif ext in TXT_EXT:
            out["title"], out["author"] = _txt_meta(path)
    except Exception:                                   # noqa: BLE001
        pass
    if not out["title"]:
        out["title"] = os.path.splitext(os.path.basename(path))[0]
    return out


def cover_bytes(path: str) -> tuple[bytes, str] | None:
    """从 EPUB 里抽封面图，返回 (字节, 扩展名)；没有封面返回 None。

    优先 `properties=cover-image`，再退回 `<meta name="cover">` 指向的 id，
    最后退回 manifest 里第一张图。命名空间按本地名匹配，EPUB 2/3 通吃。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext != EPUB_EXT:
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            name_set = set(names)

            opf = ""
            if "META-INF/container.xml" in name_set:
                for rf in ET.fromstring(zf.read("META-INF/container.xml")).iter():
                    if _local(rf) == "rootfile":
                        opf = (rf.get("full-path") or "").replace("\\", "/")
                        break
            base_dir = os.path.dirname(opf).replace("\\", "/")

            href = ""
            if opf and opf in name_set:
                root = ET.fromstring(zf.read(opf))
                cover_id = ""
                imgs: list[tuple[str, str, bool]] = []          # (id, href, is_cover)
                for el in root.iter():
                    if _local(el) == "meta":
                        if (el.get("name") or "").lower() == "cover":
                            cover_id = (el.get("content") or "").strip()
                    elif _local(el) == "item":
                        iid = el.get("id") or ""
                        h = (el.get("href") or "").replace("\\", "/")
                        props = (el.get("properties") or "").split()
                        is_cover = "cover-image" in props
                        imgs.append((iid, h, is_cover))
                        if is_cover and not href:
                            href = h
                if not href and cover_id:
                    for iid, h, _ in imgs:
                        if iid == cover_id:
                            href = h
                            break
                if not href:
                    for _, h, _ in imgs:
                        if h.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                            href = h
                            break

            if not href:
                return None
            entry = _resolve_href(base_dir, href)
            if entry not in name_set:
                return None
            data = zf.read(entry)
            if not data:
                return None
            ext2 = os.path.splitext(entry)[1].lower() or ".jpg"
            return data, ext2
    except Exception:                                       # noqa: BLE001
        return None


def cover_cached(path: str, key: str) -> tuple[str, str] | None:
    """封面落盘缓存，返回 (文件路径, content-type)。取不到返回 None。"""
    got = cover_bytes(path)
    if not got:
        return None
    data, ext = got
    os.makedirs(_COVERS_CACHE, exist_ok=True)
    out = os.path.join(_COVERS_CACHE, f"{key}{ext}")
    try:
        if (not os.path.isfile(out)) or os.path.getmtime(out) < os.path.getmtime(path):
            tmp = out + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, out)
    except OSError:
        return None
    ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/jpeg")
    return out, ctype


# ---------------------------------------------------------------------------
# 书架
# ---------------------------------------------------------------------------
def _shelf_dirs() -> list[tuple[str, str]]:
    return [
        ("收书", os.path.join(_DATA, "收书")),
        ("Kindle 书", os.path.join(_DATA, "导出", "Kindle书")),
        ("微信读书", os.path.join(_DATA, "导出", "微信读书")),
    ]


def _scan_paths() -> dict[str, str]:
    """只走文件系统，建立 key -> 路径索引（不解析元信息，很快）。"""
    idx: dict[str, str] = {}
    for _, d in _shelf_dirs():
        if not os.path.isdir(d):
            continue
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if not e.is_file() or not e.name.lower().endswith(READABLE_EXT):
                    continue
                idx[key_for(e.path)] = e.path
            except OSError:
                continue

    dev = dev_mod.find_kindle()
    if dev:
        try:
            for b in lib_mod.scan_library(dev).get("books", []):
                p = b.get("path") or ""
                if p and os.path.isfile(p) and p.lower().endswith(READABLE_EXT):
                    idx.setdefault(key_for(p), p)
        except Exception:                                   # noqa: BLE001
            pass
    return idx


def resolve_path(key: str) -> str | None:
    """把前端传进来的 key 解析成绝对路径。拒绝任何非法的 key。"""
    if not _KEY_RE.match(key or ""):
        return None
    global _INDEX
    if not _INDEX:
        _INDEX = _scan_paths()
    p = _INDEX.get(key)
    if p and os.path.isfile(p):
        return p
    _INDEX = _scan_paths()
    p = _INDEX.get(key)
    return p if p and os.path.isfile(p) else None


def refresh_index() -> None:
    global _INDEX
    _INDEX = _scan_paths()


def scan_shelf() -> list[dict]:
    """书架列表：元信息 + 阅读进度。没连 Kindle 也能正常出本机的书。"""
    paths = _scan_paths()
    _INDEX.update(paths)
    prog = load_progress()

    out: list[dict] = []
    for k, p in paths.items():
        try:
            st = os.stat(p)
        except OSError:
            continue
        m = meta(p)
        ext = os.path.splitext(p)[1].lower()
        if ext == EPUB_EXT:
            kind = "epub"
        elif ext in TXT_EXT:
            kind = "txt"
        else:
            kind = "mobi"
        # 书來源标注：按它落在哪个目录
        source = "收书"
        for label, d in _shelf_dirs():
            if os.path.dirname(p) == os.path.normpath(d):
                source = label
                break
        else:
            source = "Kindle"
        out.append({
            "key": k,
            "title": m["title"],
            "author": m["author"],
            "ext": ext,
            "kind": kind,
            "source": source,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "modified": _fmt_time(st.st_mtime),
            "drm": m["drm"],
            "needs_convert": kind != "epub",
            "last": prog.get(k) or {},
        })

    # 最近读过的排最前，其次按修改时间
    out.sort(key=lambda b: (b["last"].get("at") or 0, b.get("mtime") or 0), reverse=True)
    return out


# ---------------------------------------------------------------------------
# 让书变得能读
# ---------------------------------------------------------------------------
def _cache_out(path: str) -> str:
    os.makedirs(_BOOKS_CACHE, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(_BOOKS_CACHE, f"{key_for(path)}-{epub_mod.safe_filename(base, 40)}.epub")


def _fresh(src: str, out: str) -> bool:
    try:
        return os.path.isfile(out) and os.path.getmtime(out) >= os.path.getmtime(src)
    except OSError:
        return False


def _txt_to_epub(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            blob = f.read(_MAX_TEXT_BYTES + 1)
    except OSError as ex:
        return {"ok": False, "error": f"读不到文件：{ex}"}
    if len(blob) > _MAX_TEXT_BYTES:
        return {"ok": False, "error": "文本超过 4 MB，请改用 EPUB 版本"}
    if not blob:
        return {"ok": False, "error": "空文件"}

    enc = zcf_mod._sniff_encoding(blob)
    text = blob.decode(enc, errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    # 书名作者用「完整解码后的正文」取，别用 8 KB 头（截断会让编码嗅探翻车）
    title, author = _title_author_from_text(text, os.path.basename(path))

    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        paras = [ln.strip() for ln in text.splitlines() if ln.strip()]
    chapters: list[tuple[str, list[str]]] = []
    for i in range(0, len(paras), _CHUNK_PARAS):
        chapters.append((f"第 {i // _CHUNK_PARAS + 1} 部分", paras[i:i + _CHUNK_PARAS]))

    out = _cache_out(path)
    try:
        if not _fresh(path, out):
            made = epub_mod.build_epub(title, author, chapters, out)
            if not made.get("ok"):
                return {"ok": False, "error": made.get("error") or "打包 EPUB 失败"}
    except Exception as ex:                                # noqa: BLE001
        return {"ok": False, "error": f"打包 EPUB 失败：{ex}"}
    return {"ok": True, "path": out, "encoding": enc, "converted": True}


def _mobi_to_epub(path: str) -> dict:
    conv = conv_mod.find_ebook_convert()
    if not conv:
        return {"ok": False, "error": "没找到 Calibre（ebook-convert），转不了 MOBI/AZW3；"
                                      "先装 Calibre，或改用 EPUB 版本。",
                "need_calibre": True}
    out = _cache_out(path)
    if _fresh(path, out):
        return {"ok": True, "path": out, "converted": True, "cached": True}
    try:
        proc = subprocess.run(
            [conv, path, out],
            capture_output=True, timeout=900,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError) as ex:
        return {"ok": False, "error": f"调用 Calibre 失败：{ex}"}
    if not (os.path.isfile(out) and os.path.getsize(out) > 0):
        detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
        return {"ok": False, "error": f"Calibre 转换失败：{detail[-400:]}"}
    return {"ok": True, "path": out, "converted": True}


def ensure_readable(path: str) -> dict:
    """返回一份「epub.js 能直接读」的 EPUB 路径。失败时带人话错误。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == EPUB_EXT:
        return {"ok": True, "path": path, "converted": False}
    if ext in TXT_EXT:
        return _txt_to_epub(path)
    if ext in MOBI_EXT:
        return _mobi_to_epub(path)
    return {"ok": False, "error": f"暂不支持的格式：{ext}"}


# ---------------------------------------------------------------------------
# 阅读进度 / 标注（纯本地 JSON）
# ---------------------------------------------------------------------------
def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:                                       # noqa: BLE001
        return {}


def _write_json(path: str, data: dict) -> bool:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def load_progress() -> dict:
    with _lock:
        return _read_json(PROGRESS_PATH)


def save_progress(key: str, percent: float = 0, cfi: str = "", chapter: str = "") -> dict:
    if not _KEY_RE.match(key or ""):
        return {"ok": False, "error": "无效的书目标识"}
    with _lock:
        data = _read_json(PROGRESS_PATH)
        cur = data.get(key) or {}
        cur.update({"percent": round(float(percent or 0), 4), "cfi": cfi,
                    "chapter": chapter, "at": int(time.time())})
        data[key] = cur
        if not _write_json(PROGRESS_PATH, data):
            return {"ok": False, "error": "写不进书架目录，检查磁盘权限"}
    return {"ok": True, "last": data[key]}


def load_annots() -> dict:
    with _lock:
        return _read_json(ANNOT_PATH)


def annots_of(key: str) -> list[dict]:
    return list(load_annots().get(key) or [])


def add_annot(key: str, text: str, cfi: str = "", note: str = "", chapter: str = "") -> dict:
    if not _KEY_RE.match(key or ""):
        return {"ok": False, "error": "无效的书目标识"}
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "标注内容为空"}
    item = {
        "id": hashlib.sha1(f"{key}|{cfi}|{text}".encode("utf-8")).hexdigest()[:12],
        "text": text[:2000],
        "cfi": cfi,
        "note": (note or "").strip()[:2000],
        "chapter": chapter,
        "at": int(time.time()),
    }
    with _lock:
        data = _read_json(ANNOT_PATH)
        lst = data.get(key) or []
        if not any(a.get("id") == item["id"] for a in lst):
            lst.insert(0, item)
        data[key] = lst
        if not _write_json(ANNOT_PATH, data):
            return {"ok": False, "error": "写不进书架目录，检查磁盘权限"}
    return {"ok": True, "item": item}


def remove_annot(key: str, annot_id: str) -> bool:
    with _lock:
        data = _read_json(ANNOT_PATH)
        lst = data.get(key) or []
        left = [a for a in lst if a.get("id") != annot_id]
        if len(left) == len(lst):
            return False
        if left:
            data[key] = left
        else:
            data.pop(key, None)
        return _write_json(ANNOT_PATH, data)
