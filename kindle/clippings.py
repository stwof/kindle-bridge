# -*- coding: utf-8 -*-
"""解析 Kindle 的 My Clippings.txt（中英文两种格式）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .device import read_text

SEPARATOR = "=========="

# 位置 / 页码 / 时间
RE_LOCATION = re.compile(r"(?:位置|Location)\s*#?\s*([\d,\-]+)")
RE_PAGE_CN = re.compile(r"第\s*(\d+)\s*页")
RE_PAGE_EN = re.compile(r"on\s+page\s+(\d+)", re.I)
RE_TIME_CN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日.*?(?:(上午|下午|凌晨|晚上))?\s*(\d{1,2}):(\d{2}):(\d{2})")
RE_TIME_EN = re.compile(
    r"([A-Za-z]+),\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)?",
    re.I,
)

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

TYPE_MAP = (
    (("标注", "Highlight"), "highlight"),
    (("笔记", "Note"), "note"),
    (("书签", "Bookmark"), "bookmark"),
)

# 明显不是作者名的括注
NON_AUTHOR_HINTS = (
    "免费公版书", "公版书", "系列", "书系", "套装", "全集", "文集", "译林", "读品",
    "edition", "新版", "修订", "全注", "典藏", "精装", "插图", "无障碍",
)


@dataclass
class Clip:
    title: str
    author: str
    type: str          # highlight / note / bookmark
    location: str      # "3749-3749" 或 ""
    page: str          # "298" 或 ""
    added_at: str      # ISO 8601 或原文
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def strip_series(title: str) -> str:
    """去掉书名结尾的丛书 / 版本括注，如「(中国古典文学书系)」。"""
    pattern = re.compile(r"\s*[（(]([^（()）]*)[)）]\s*$")
    while True:
        m = pattern.search(title)
        if not m:
            break
        if not any(h.lower() in m.group(1).lower() for h in NON_AUTHOR_HINTS):
            break
        stripped = title[: m.start()].strip()
        if not stripped:
            break
        title = stripped
    return title


def _split_title_author(line: str) -> tuple[str, str]:
    """从 `书名 (作者)` 中拆出书名与作者（尽力而为）。"""
    line = line.strip()
    groups = list(re.finditer(r"[（(]([^（()）]*)[)）]", line))
    if not groups:
        return strip_series(line), ""
    for m in reversed(groups):
        inner = m.group(1).strip()
        low = inner.lower()
        if not inner:
            continue
        if any(h.lower() in low for h in NON_AUTHOR_HINTS):
            continue
        title = (line[: m.start()] + line[m.end():]).strip()
        if title:
            return strip_series(title), inner
    return strip_series(line), ""


def _parse_date(block: str) -> str:
    m = RE_TIME_CN.search(block)
    if m:
        y, mo, d, period, hh, mm, ss = m.groups()
        h = int(hh)
        if period in ("下午", "晚上") and h < 12:
            h += 12
        elif period in ("上午", "凌晨") and h == 12:
            h = 0
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {h:02d}:{int(mm):02d}:{int(ss):02d}"
    m = RE_TIME_EN.search(block)
    if m:
        _, month, day, year, hh, mm, ss, ampm = m.groups()
        mo = MONTHS.get(month.lower())
        if mo:
            h = int(hh)
            if ampm:
                if ampm.upper() == "PM" and h < 12:
                    h += 12
                elif ampm.upper() == "AM" and h == 12:
                    h = 0
            return f"{int(year):04d}-{mo:02d}-{int(day):02d} {h:02d}:{int(mm):02d}:{int(ss):02d}"
    return ""


def _parse_type(head: str) -> str:
    for keys, kind in TYPE_MAP:
        if any(k in head for k in keys):
            return kind
    return "unknown"


def parse_clippings(path: str, dedupe: bool = True) -> list[Clip]:
    """解析 My Clippings.txt，返回按出现顺序排列的标注列表。"""
    raw = read_text(path)
    if not raw:
        return []

    clips: list[Clip] = []
    for block in raw.split(SEPARATOR):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        title_line, head = lines[0], lines[1]
        if not head.lstrip().startswith("-"):
            # 容错：第二行不是条目信息行
            continue
        title, author = _split_title_author(title_line)
        body = "\n".join(lines[2:]).strip()

        loc = RE_LOCATION.search(head)
        page = RE_PAGE_CN.search(head) or RE_PAGE_EN.search(head)
        clips.append(Clip(
            title=title,
            author=author,
            type=_parse_type(head),
            location=loc.group(1) if loc else "",
            page=page.group(1) if page else "",
            added_at=_parse_date(head),
            text=body,
        ))

    if dedupe:
        clips = _dedupe(clips)
    return clips


def _dedupe(clips: list[Clip]) -> list[Clip]:
    """同一位置的重复记录只保留文本最长的一条。"""
    best: dict[tuple, Clip] = {}
    order: list[tuple] = []
    for c in clips:
        key = (c.title, c.type, c.location, c.page)
        if c.type == "highlight":
            # 同位置文本会逐步补全，取最长
            if key not in best:
                best[key] = c
                order.append(key)
            elif len(c.text) > len(best[key].text):
                best[key] = c
        else:
            key2 = (c.title, c.type, c.location, c.page, c.text)
            if key2 not in best:
                best[key2] = c
                order.append(key2)
    return [best[k] for k in order]


def group_by_book(clips: list[Clip]) -> list[dict]:
    """按书分组，保持首次出现顺序。"""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for c in clips:
        g = groups.get(c.title)
        if g is None:
            g = {"title": c.title, "author": c.author, "items": []}
            groups[c.title] = g
            order.append(c.title)
        if not g["author"] and c.author:
            g["author"] = c.author
        g["items"].append({
            "type": c.type,
            "location": c.location,
            "page": c.page,
            "added_at": c.added_at,
            "text": c.text,
        })
    return [groups[t] for t in order]
