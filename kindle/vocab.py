# -*- coding: utf-8 -*-
"""读取 Kindle 生词本 (system/vocabulary/vocab.db)。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone


def _ts_to_iso(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def read_vocab(db_path: str) -> dict:
    """返回 {words:[...], books:[...], stats:{...}}；不可读时返回空结构。"""
    empty = {"words": [], "books": [], "stats": {"total": 0, "zh": 0, "en": 0, "lookups": 0}}
    if not os.path.isfile(db_path):
        return empty

    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return empty

    try:
        cur = con.cursor()
        tables = {r[0].upper() for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

        books = {}
        if "BOOK_INFO" in tables:
            for bid, title, authors in cur.execute(
                    "SELECT id, title, authors FROM BOOK_INFO"):
                books[bid] = {"title": title or "", "authors": authors or ""}

        words = {}
        if "WORDS" in tables:
            for wid, word, lang, ts in cur.execute(
                    "SELECT id, word, lang, timestamp FROM WORDS"):
                words[wid] = {
                    "id": wid,
                    "word": word or "",
                    "lang": lang or "",
                    "added_at": _ts_to_iso(ts),
                    "lookups": 0,
                    "last_lookup": "",
                    "contexts": [],
                    "books": [],
                }

        lookups = []
        if "LOOKUPS" in tables:
            for word_key, book_key, usage, ts in cur.execute(
                    "SELECT word_key, book_key, usage, timestamp FROM LOOKUPS"):
                lookups.append((word_key, book_key, usage or "", ts or 0))
        lookups.sort(key=lambda x: x[3])

        for word_key, book_key, usage, ts in lookups:
            info = words.get(word_key)
            if info is None:
                continue
            info["lookups"] += 1
            info["last_lookup"] = _ts_to_iso(ts) or info["last_lookup"]
            title = books.get(book_key, {}).get("title", "")
            if title and title not in info["books"]:
                info["books"].append(title)
            if usage and len(info["contexts"]) < 5:
                info["contexts"].append({"text": usage.strip(), "book": title})

        word_list = sorted(words.values(), key=lambda w: w["last_lookup"] or w["added_at"], reverse=True)
        lang_count = {"zh": 0, "en": 0}
        for w in word_list:
            if w["lang"] in lang_count:
                lang_count[w["lang"]] += 1

        return {
            "words": word_list,
            "books": [{"id": k, **v} for k, v in books.items()],
            "stats": {
                "total": len(word_list),
                "zh": lang_count["zh"],
                "en": lang_count["en"],
                "lookups": len(lookups),
            },
        }
    except sqlite3.Error:
        return empty
    finally:
        con.close()
