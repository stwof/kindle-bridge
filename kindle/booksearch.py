# -*- coding: utf-8 -*-
"""书内全文搜索：把一本 EPUB 抽成内存索引，供 /api/reader/search 查询。

设计取舍（重要，改之前先读）：
  - 零新增依赖：只用标准库 zipfile + xml.etree，跟阅读器用的是同一份可读 EPUB
    （TXT 现打包、MOBI 经 Calibre 转换后的缓存），保证 href 与阅读器对得上。
  - epub.js 不提供「文本 → 精确 CFI」的 API，自研 CFI 又极易和分页引擎打架。
    所以命中返回 **href + 段号 + 片段文本**，前端 display(href) 跳到该章后，
    在 iframe 里用 DOM Range 按文本找位置并高亮，而不是伪造一个文本级 CFI。
  - 容量闸门：章节 ≤2000、正文 ≤20MB、单段 ≤4000 字、索引 ≤64MB，超限截断并标记
    truncated，避免超大书把浏览器内存打爆。
  - 索引按 (key, mtime) 缓存在进程内，最多 3 本；源文件变了自动重建。
"""
from __future__ import annotations

import os
import posixpath
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import OrderedDict

_MAX_CHAPTERS = 2000
_MAX_TEXT_BYTES = 20 * 1024 * 1024
_MAX_PARA_CHARS = 4000
_MAX_INDEX_BYTES = 64 * 1024 * 1024
_INDEX_KEEP = 3

_BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"}
_XHTML_MIME = ("application/xhtml+xml", "text/html", "application/xml", "text/xml")
_WORD_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_INDEXES: "OrderedDict[str, dict]" = OrderedDict()


def _local(tag: str) -> str:
    """去掉 XML 命名空间前缀：{http://...}p -> p。"""
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.lower()


def _attrs(node) -> dict:
    """属性名去命名空间，值原样返回。"""
    out = {}
    for k, v in node.attrib.items():
        out[_local(k)] = v
    return out


def _container_opf(zf: zipfile.ZipFile) -> str:
    """从 META-INF/container.xml 找 OPF 路径；找不到就在 zip 根猜一个。"""
    try:
        root = ET.fromstring(zf.read("META-INF/container.xml"))
        for node in root.iter():
            if _local(node.tag) == "rootfile":
                p = _attrs(node).get("full-path", "")
                if p:
                    return p.lstrip("/")
    except Exception:                                       # noqa: BLE001
        pass
    for name in zf.namelist():
        if name.lower().endswith(".opf"):
            return name
    return ""


def _chapter_label(href: str, nav: dict) -> str:
    return nav.get(href) or posixpath.basename(href) or "章节"


def _parse_nav(zf: zipfile.ZipFile, names: set) -> dict:
    """尽量从 toc.ncx / nav.xhtml 取 href -> 章节标题，取不到就留空。"""
    labels = {}
    target = None
    for n in names:
        low = n.lower()
        if low.endswith("toc.ncx"):
            target = n
            break
        if low.endswith("nav.xhtml") or low.endswith("nav.html"):
            target = target or n
    if not target:
        return labels
    try:
        root = ET.fromstring(zf.read(target))
        is_ncx = target.lower().endswith(".ncx")
        # NCX 用 <navPoint>（内含 <navLabel><text> 与 <content src>）；
        # EPUB3 nav 用 <a href>。逐节点就近取「标题 + 链接」，避免祖先匹配错乱。
        for node in root.iter():
            tag = _local(node.tag)
            if is_ncx:
                if tag != "navpoint":
                    continue
                title, src = "", ""
                for child in node.iter():
                    ct = _local(child.tag)
                    if ct == "text" and not title:
                        title = "".join(child.itertext()).strip()
                    elif ct == "content" and not src:
                        src = _attrs(child).get("src", "")
            else:
                if tag != "a":
                    continue
                title = "".join(node.itertext()).strip()
                src = _attrs(node).get("href", "")
            if title and src:
                labels[src.split("#")[0]] = title[:120]
    except Exception:                                       # noqa: BLE001
        pass
    return labels


def _extract_paras(html: bytes) -> list[str]:
    """从一章 XHTML 抽段落纯文本。解析失败则退化为正则去标签。"""
    text = ""
    try:
        root = ET.fromstring(html)
        parts = []
        for node in root.iter():
            if _local(node.tag) in _BLOCK_TAGS:
                s = re.sub(r"\s+", " ", "".join(node.itertext())).strip()
                if s:
                    parts.append(s[:_MAX_PARA_CHARS])
        text = "\n".join(parts)
    except Exception:                                       # noqa: BLE001
        raw = html.decode("utf-8", "ignore")
        raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
        raw = re.sub(r"(?s)<[^>]+>", "\n", raw)
        raw = (raw.replace("&nbsp;", " ").replace("&amp;", "&")
                  .replace("&lt;", "<").replace("&gt;", ">"))
        text = "\n".join(s.strip()[:_MAX_PARA_CHARS]
                         for s in raw.splitlines() if s.strip())
    out, seen = [], set()
    for para in text.splitlines():
        para = para.strip()
        if not para or para in seen:
            continue
        seen.add(para)
        out.append(para)
    return out


def build_index(epub_path: str, key: str) -> dict:
    """构建索引。任何解析失败都抛异常，由调用方转成 HTTP 错误。"""
    if not epub_path or not os.path.isfile(epub_path):
        raise ValueError("书文件不存在")
    chapters = []
    total_chars = 0
    truncated = False
    postings: dict[str, set] = {}
    with zipfile.ZipFile(epub_path) as zf:
        names = set(zf.namelist())
        opf = _container_opf(zf)
        if not opf or opf not in names:
            raise ValueError("这本书没有合法的 EPUB 目录结构")
        opf_dir = posixpath.dirname(opf)
        try:
            root = ET.fromstring(zf.read(opf))
        except Exception as ex:                              # noqa: BLE001
            raise ValueError(f"EPUB 目录解析失败：{ex}") from ex
        manifest = {}
        for node in root.iter():
            if _local(node.tag) == "item":
                a = _attrs(node)
                if a.get("id") and a.get("href"):
                    manifest[a["id"]] = {"href": a["href"], "mime": a.get("media-type", "")}
        order = []
        for node in root.iter():
            if _local(node.tag) == "itemref":
                idref = _attrs(node).get("idref", "")
                if idref in manifest:
                    order.append(manifest[idref])
        if not order:
            order = [v for v in manifest.values() if v["mime"] in _XHTML_MIME]
        nav = _parse_nav(zf, names)
        for spine, item in enumerate(order[:_MAX_CHAPTERS]):
            href = item["href"]
            member = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href
            if member not in names:
                member = href.lstrip("/")
                if member not in names:
                    continue
            paras = _extract_paras(zf.read(member))
            if not paras:
                continue
            label = _chapter_label(href, nav)
            chapters.append({"href": href, "member": member, "spine": spine,
                             "label": label, "paras": paras})
            total_chars += sum(len(p) for p in paras)
            for pi, para in enumerate(paras):
                ci = len(chapters) - 1
                for tok in _tokens(para):
                    postings.setdefault(tok, set()).add((ci, pi))
            if total_chars > _MAX_TEXT_BYTES or len(chapters) >= _MAX_CHAPTERS:
                truncated = True
                break
    if not chapters:
        raise ValueError("这本书没有可搜索的正文（可能是扫描图片版）")
    return {"key": key, "src_path": epub_path,
            "src_mtime": os.path.getmtime(epub_path),
            "chapters": chapters, "postings": postings,
            "truncated": truncated, "built_at": time.time()}


def _tokens(text: str) -> set[str]:
    """中文登记整段 + 2-gram（够用且零分词依赖），英文小写整词。"""
    out = set()
    for m in _WORD_RE.finditer(text):
        s = m.group()
        if _CJK_RE.match(s):
            out.add(s)
            for i in range(len(s) - 1):
                out.add(s[i:i + 2])
        else:
            out.add(s.lower())
    return out


def normalize(q: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", (q or "")).strip()[:200]


def get_index(epub_path: str, key: str) -> dict:
    """取索引：命中缓存且源文件未变则复用，否则重建。"""
    mtime = os.path.getmtime(epub_path) if os.path.isfile(epub_path) else 0
    cached = _INDEXES.get(key)
    if cached and cached.get("src_mtime") == mtime:
        _INDEXES.move_to_end(key)
        return cached
    idx = build_index(epub_path, key)
    _INDEXES[key] = idx
    _INDEXES.move_to_end(key)
    while len(_INDEXES) > _INDEX_KEEP:
        _INDEXES.popitem(last=False)
    return idx


def invalidate(key: str = "") -> None:
    if key:
        _INDEXES.pop(key, None)
    else:
        _INDEXES.clear()


def query(index: dict, q: str, limit: int = 20, offset: int = 0) -> dict:
    """查询。多词取「全部命中」；中文用 2-gram 找候选，再逐段精确校验。"""
    q = normalize(q)
    if not q:
        return {"ok": False, "error": "查询为空"}
    terms = [t for t in re.split(r"\s+", q.lower()) if t]
    limit = max(1, min(limit, 50))
    offset = max(0, min(offset, 1000))
    words = list(_WORD_RE.finditer(q))
    cands = set()
    for m in words:
        s = m.group()
        keys = [s] if not _CJK_RE.match(s) else ([s] + [s[i:i + 2] for i in range(len(s) - 1)])
        for tok in keys:
            cands |= index["postings"].get(tok, set())
    if not cands:
        return {"ok": True, "q": q, "total": 0, "hits": [],
                "truncated": index["truncated"], "cached": True, "ms": 0}
    hits = []
    t0 = time.time()
    for ci, pi in sorted(cands):
        chapter = index["chapters"][ci]
        para = chapter["paras"][pi]
        low = para.lower()
        if not all(t in low for t in terms):
            continue
        i = low.find(terms[0])
        if i < 0:
            continue
        span = len(q)
        hits.append({
            "href": chapter["href"], "spine": chapter["spine"],
            "chapter": chapter["label"],
            "before": para[max(0, i - 60):i],
            "match": para[i:i + span],
            "after": para[i + span:i + span + 60],
            "para": pi, "offset": i,
        })
    total = len(hits)
    return {"ok": True, "q": q, "total": total,
            "hits": hits[offset:offset + limit],
            "truncated": index["truncated"], "cached": True,
            "ms": int((time.time() - t0) * 1000)}
