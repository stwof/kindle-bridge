# -*- coding: utf-8 -*-
"""把标注与生词导出成 Markdown / CSV / JSON / Zotero 等目标格式。"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime

TYPE_LABEL = {"highlight": "标注", "note": "笔记", "bookmark": "书签"}
TYPE_LABEL_EN = {"highlight": "Highlight", "note": "Note", "bookmark": "Bookmark"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe(name: str) -> str:
    from .convert import safe_filename
    return safe_filename(name)


def _loc(item: dict) -> str:
    parts = []
    if item.get("page"):
        parts.append(f"第 {item['page']} 页")
    if item.get("location"):
        parts.append(f"位置 {item['location']}")
    return " · ".join(parts)


def highlights_markdown(groups: list[dict], device: dict | None = None) -> dict[str, str]:
    """每本书一个 Markdown 文件，外加一个总索引。"""
    files: dict[str, str] = {}
    index_lines = ["# Kindle 标注导出", ""]
    if device:
        index_lines.append(f"- 设备：{device.get('name', 'Kindle')}（{device.get('root', '')}）")
    index_lines.append(f"- 导出时间：{_now()}")
    index_lines.append(f"- 书籍数：{len(groups)}　标注数：{sum(len(g['items']) for g in groups)}")
    index_lines.append("")
    index_lines.append("## 目录")
    for g in groups:
        title = g["title"]
        index_lines.append(f"- [{title}](#{_safe(title)}) — {len(g['items'])} 条")
    index_lines.append("")

    for g in groups:
        title = g["title"]
        author = g.get("author") or "未知作者"
        lines = [f"# {title}", "", f"> {author}", ""]
        for it in g["items"]:
            label = TYPE_LABEL.get(it["type"], "标注")
            meta = " · ".join(x for x in (_loc(it), it.get("added_at", "")) if x)
            text = it["text"] or "（无内容）"
            if it["type"] == "highlight":
                lines.append(f"> {text}")
            else:
                lines.append(f"**{label}**：{text}")
            if meta:
                lines.append(f"<sub>{label} · {meta}</sub>")
            lines.append("")
        files[f"标注/{_safe(title)}.md"] = "\n".join(lines)

    files["标注/全部标注.md"] = "\n".join(index_lines)
    return files


def highlights_csv(groups: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["书名", "作者", "类型", "页码", "位置", "时间", "内容"])
    for g in groups:
        for it in g["items"]:
            w.writerow([g["title"], g.get("author", ""), TYPE_LABEL.get(it["type"], ""),
                        it.get("page", ""), it.get("location", ""), it.get("added_at", ""),
                        it["text"]])
    return buf.getvalue()


def highlights_json(groups: list[dict], device: dict | None = None) -> str:
    return json.dumps({
        "generator": "Kindle 桥",
        "exported_at": _now(),
        "device": device or {},
        "books": groups,
    }, ensure_ascii=False, indent=2)


def weread_text(groups: list[dict]) -> str:
    """生成可直接粘贴到微信读书「想法/笔记」的纯文本。"""
    out = []
    out.append("我的 Kindle 读书笔记")
    out.append(f"导出时间：{_now()}")
    out.append("")
    for g in groups:
        out.append("=" * 28)
        out.append(f"《{g['title']}》")
        if g.get("author"):
            out.append(g["author"])
        out.append("=" * 28)
        out.append("")
        n = 0
        for it in g["items"]:
            if it["type"] != "highlight" or not it["text"]:
                continue
            n += 1
            out.append(f"{n}. {it['text']}")
        if n == 0:
            out.append("（本书暂无划线摘录）")
        out.append("")
    return "\n".join(out)


def vocab_markdown(words: list[dict]) -> str:
    lines = ["# Kindle 生词本", "", f"导出时间：{_now()}　共 {len(words)} 个词", ""]
    for w in words:
        head = f"## {w['word']}"
        meta = []
        if w.get("lang"):
            meta.append("中文" if w["lang"] == "zh" else "英文")
        if w.get("lookups"):
            meta.append(f"查询 {w['lookups']} 次")
        if w.get("last_lookup"):
            meta.append(w["last_lookup"])
        lines.append(head)
        if meta:
            lines.append(f"<sub>{' · '.join(meta)}</sub>")
        for c in w.get("contexts", []):
            lines.append(f"> {c['text']}")
            if c.get("book"):
                lines.append(f"> —— 《{c['book']}》")
        lines.append("")
    return "\n".join(lines)


def vocab_csv(words: list[dict]) -> str:
    """Anki / Excel 友好的 CSV。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["单词", "语言", "查询次数", "最近查询", "首条例句", "出处"])
    for it in words:
        ctx = it.get("contexts") or [{}]
        w.writerow([it["word"], "中文" if it.get("lang") == "zh" else "英文",
                    it.get("lookups", 0), it.get("last_lookup", ""),
                    ctx[0].get("text", ""), ctx[0].get("book", "")])
    return buf.getvalue()


def vocab_anki_csv(words: list[dict]) -> str:
    """Anki 导入用（正面 / 背面 / 标签，制表符分隔）。"""
    buf = io.StringIO()
    buf.write("#separator:tab\n#html:false\n#columns:正面\t背面\t标签\n")
    for it in words:
        ctx = (it.get("contexts") or [{}])[0]
        back = ctx.get("text", "")
        if ctx.get("book"):
            back = f"{back}\n——《{ctx['book']}》" if back else f"——《{ctx['book']}》"
        tag = "kindle " + ("中文" if it.get("lang") == "zh" else "英文")
        buf.write(f"{it['word']}\t{back}\t{tag}\n")
    return buf.getvalue()


def make_zip(files: dict[str, str]) -> bytes:
    """把 {相对路径: 文本} 打包成 zip 字节流。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content.encode("utf-8"))
    return buf.getvalue()


def build_export(kind: str, groups: list[dict], words: list[dict],
                 device: dict | None = None) -> tuple[str, bytes, str]:
    """返回 (下载文件名, 字节内容, MIME)。kind 见常见取值。"""
    dev = device or {}
    if kind == "highlights-md":
        return ("Kindle标注_Markdown.zip", make_zip(highlights_markdown(groups, dev)), "application/zip")
    if kind == "highlights-csv":
        return ("Kindle标注.csv", highlights_csv(groups).encode("utf-8-sig"), "text/csv")
    if kind == "highlights-json":
        return ("Kindle标注.json", highlights_json(groups, dev).encode("utf-8"), "application/json")
    if kind == "weread-txt":
        return ("微信读书笔记.txt", weread_text(groups).encode("utf-8"), "text/plain")
    if kind == "vocab-csv":
        return ("Kindle生词本.csv", vocab_csv(words).encode("utf-8-sig"), "text/csv")
    if kind == "vocab-anki":
        return ("Kindle生词_Anki.txt", vocab_anki_csv(words).encode("utf-8"), "text/plain")
    if kind == "vocab-md":
        return ("Kindle生词本.md", vocab_markdown(words).encode("utf-8"), "text/markdown")
    if kind == "all":
        files = {}
        files.update(highlights_markdown(groups, dev))
        files["标注/Kindle标注.csv"] = highlights_csv(groups)
        files["标注/Kindle标注.json"] = highlights_json(groups, dev)
        files["微信读书笔记.txt"] = weread_text(groups)
        files["生词本/Kindle生词本.md"] = vocab_markdown(words)
        files["生词本/Kindle生词本.csv"] = vocab_csv(words)
        files["生词本/Kindle生词_Anki.txt"] = vocab_anki_csv(words)
        return ("Kindle桥_全部导出.zip", make_zip(files), "application/zip")
    raise ValueError(f"未知导出类型: {kind}")
