# -*- coding: utf-8 -*-
"""免费书源扩展单测：Open Library / 维基文库 解析与路由（不依赖联网）。

本机代理会拦公版书站，所以这里把 freebooks._get 替换成本地缓存好的真实返回结构，
只验证「解析逻辑 + 单源路由」是否正确。真实联网取数在用户正常网络下由运行期负责。
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kindle import freebooks as fb

ok = fail = 0
def chk(cond, msg):
    global ok, fail
    if cond:
        ok += 1; print("  [OK] ", msg)
    else:
        fail += 1; print("  [FAIL]", msg)

# 下面两份是真实接口返回结构（字段名逐字节对齐实测）：
#  Open Library search.json → docs[].{title,author_name,cover_i,ia,key,edition_count,language,has_fulltext}
#  Wikisource MediaWiki API → query.search[].{ns,title,pageid} / query.searchinfo.totalhits
OL_JSON = json.dumps({
    "numFound": 2361, "start": 0,
    "docs": [
        {"title": "Pride and Prejudice", "author_name": ["Jane Austen"], "cover_i": 14348537,
         "ia": ["prideandprejudic42671gut"], "key": "/works/OL66554W", "edition_count": 4042,
         "first_publish_year": 1813, "has_fulltext": True, "language": ["eng", "chi"]},
        {"title": "紅樓夢", "author_name": ["曹雪芹"], "cover_i": None,
         "ia": ["hongloumeng00tsao"], "key": "/works/OL9W", "edition_count": 10,
         "has_fulltext": True, "language": ["chi"]},
    ]
}).encode()
WS_JSON = json.dumps({
    "batchcomplete": "",
    "query": {
        "searchinfo": {"totalhits": 42},
        "search": [
            {"ns": 0, "title": "Pride and Prejudice", "pageid": 123,
             "snippet": "…", "wordcount": 120000, "timestamp": "2020-01-01T00:00:00Z"},
            {"ns": 0, "title": "Alice's Adventures in Wonderland", "pageid": 456,
             "snippet": "…", "wordcount": 30000, "timestamp": "2020-01-01T00:00:00Z"},
        ],
    }
}).encode()


def fake_get(url, *a, **k):
    if "openlibrary.org" in url:
        return OL_JSON
    if "wikisource.org" in url:
        return WS_JSON
    raise AssertionError("unexpected url " + url)


fb._get = fake_get


print("== Open Library 解析 ==")
r = fb._open_library("pride", "", 1)
chk(len(r["items"]) == 2, f"解析出 {len(r['items'])} 条")
it = r["items"][0]
chk(it["source"] == "openlibrary" and it["source_name"] == "Open Library", "source 字段正确")
chk(it["title"] == "Pride and Prejudice", "标题正确")
chk(it["author"] == "Jane Austen", "作者正确")
chk(it["cover"].startswith("https://covers.openlibrary.org/b/id/"), "封面用 OL covers 接口")
chk(any(f["ext"] == ".epub" and "archive.org" in f["url"] for f in it["files"]), "带 IA EPUB 链接")
chk(any(f["ext"] == ".txt" and "archive.org" in f["url"] for f in it["files"]), "带 IA 纯文本链接")
chk("zh" in it["langs"] and "en" in it["langs"], "MARC 语言码已翻成两字母显示")

print("== Open Library 中文 ==")
r2 = fb._open_library("紅樓夢", "zh", 1)
zh_item = next(i for i in r2["items"] if i["title"] == "紅樓夢")
chk(zh_item["langs"] == ["zh"], "中文检索语言标 zh")
chk("zh.wikisource" not in zh_item["page_url"], "OL 不混用 wiki 链接")

print("== 维基文库 解析 ==")
r3 = fb._wikisource("pride", "en", 1)
chk(len(r3["items"]) == 2, f"解析出 {len(r3['items'])} 条")
w = r3["items"][0]
chk(w["source"] == "wikisource" and w["source_name"] == "维基文库", "source 字段正确")
chk(w["title"] == "Pride and Prejudice", "标题正确")
chk(w["files"][0]["ext"] == ".epub" and "ws-export.wmcloud.org" in w["files"][0]["url"], "EPUB 走 ws-export")
chk("en.wikisource.org/wiki/" in w["page_url"], "page_url 指向 en.wikisource")

print("== 维基文库 中文子域 ==")
r4 = fb._wikisource("紅樓夢", "zh", 1)
chk("zh.wikisource.org" in r4["items"][0]["page_url"], "中文切到 zh.wikisource")

print("== SOURCES 已登记 ==")
ids = {s["id"] for s in fb.SOURCES}
chk("openlibrary" in ids and "wikisource" in ids, "两个新书源已进 SOURCES")

print("== search() 单源路由 ==")
r5 = fb.search("pride", source="openlibrary", lang="", page=1)
chk(all(i["source"] == "openlibrary" for i in r5["items"]), "source=openlibrary 只回 OL")
r6 = fb.search("pride", source="wikisource", lang="en", page=1)
chk(all(i["source"] == "wikisource" for i in r6["items"]), "source=wikisource 只回 WS")

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
