# -*- coding: utf-8 -*-
"""阅读器增强测试：书内全文搜索 + 书签持久化。

全程用临时目录 + 内存造的 EPUB，不碰用户数据、不联网。
覆盖：中文 2-gram/英文、多词交集、limit/offset、缓存失效、书签 CRUD/幂等/
软删除/损坏 JSON 容错/非法 key，以及 /api/reader/* 的 HTTP 冒烟。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from kindle import booksearch as BS                                  # noqa: E402
from kindle import reader as R                                       # noqa: E402

ok = fail = 0


def chk(cond, msg):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK]  ", msg)
    else:
        fail += 1
        print("  [FAIL]", msg)


def section(t):
    print(f"\n--- {t} ---")


TMP = tempfile.mkdtemp(prefix="kb-search-")
SHELF = os.path.join(TMP, "bookshelf")
os.makedirs(SHELF, exist_ok=True)
R.BOOKMARK_PATH = os.path.join(SHELF, "bookmarks.json")

CH1 = ("第一章 羞耻感。慢性羞耻感是一种深层的情绪体验。",
       "人们常常把羞耻感与内疚混为一谈。理解羞耻感需要共情。")
CH2 = ("Chapter Two. Shame and empathy. The reader feel shame deeply.",
       "共情和理解是心理治疗的核心。Shame can be healed.")


def make_epub(path):
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bid">
 <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>羞耻感研究</dc:title><dc:creator>测试</dc:creator></metadata>
 <manifest>
  <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
  <item id="c2" href="chap2.xhtml" media-type="application/xhtml+xml"/>
 </manifest>
 <spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>"""
    cont = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
 <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    ncx = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head/>
<docTitle><text>羞耻感研究</text></docTitle><navMap>
<navPoint id="n1" playOrder="1"><navLabel><text>第一章 羞耻感</text></navLabel><content src="chap1.xhtml"/></navPoint>
<navPoint id="n2" playOrder="2"><navLabel><text>第二章 Shame</text></navLabel><content src="chap2.xhtml"/></navPoint>
</navMap></ncx>"""
    def xhtml(paras):
        body = "".join(f"<p>{p}</p>" for p in paras)
        return ("<?xml version='1.0' encoding='UTF-8'?>"
                "<html xmlns='http://www.w3.org/1999/xhtml'><body>" + body + "</body></html>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/container.xml", cont)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/toc.ncx", ncx)
        z.writestr("OEBPS/chap1.xhtml", xhtml(CH1))
        z.writestr("OEBPS/chap2.xhtml", xhtml(CH2))


EPUB = os.path.join(TMP, "book.epub")
make_epub(EPUB)

section("全文搜索 · 索引与查询")
idx = BS.build_index(EPUB, "a" * 16)
chk(len(idx["chapters"]) == 2, "正确抽出两章")
chk(idx["chapters"][0]["label"] == "第一章 羞耻感", "章节标题来自 NCX")

r = BS.query(idx, "羞耻感")
chk(r["ok"] and r["total"] >= 1, f"中文查询命中（total={r['total']}）")
chk(any(h["match"] == "羞耻感" for h in r["hits"]), "命中词精确为「羞耻感」")
chk(all(h["href"] and "chapter" in h for h in r["hits"]), "命中带 href/章节")

r2 = BS.query(idx, "shame")
chk(r2["ok"] and r2["total"] >= 1, f"英文查询命中（total={r2.get('total')}）")

r3 = BS.query(idx, "羞耻感 共情")
chk(r3["ok"] and r3["total"] >= 1, "多词交集命中")

r4 = BS.query(idx, "羞耻感", limit=1, offset=0)
chk(len(r4["hits"]) == 1, "limit 生效")
chk(r4["total"] >= r["total"] - r["total"], "total 为截断前计数")

chk(not BS.query(idx, "")["ok"], "空查询返回错误")
chk(not BS.query(idx, "   ")["ok"], "纯空白查询返回错误")

# 缓存：同一路径命中缓存对象
i1 = BS.get_index(EPUB, "k1")
i2 = BS.get_index(EPUB, "k1")
chk(i1 is i2, "索引按 key 缓存复用")
BS.invalidate("k1")
i3 = BS.get_index(EPUB, "k1")
chk(i1 is not i3, "invalidate 后重建")

section("书签 · CRUD / 幂等 / 软删除 / 容错")
KEY = "b" * 16
a = R.add_bookmark(KEY, cfi="epubcfi(/6/4)", href="chap1.xhtml",
                   chapter="第一章", excerpt="羞耻感是一种深层情绪")
chk(a["ok"], "新增书签成功")
bid = a["item"]["id"]
chk(len(R.bookmarks_of(KEY)) == 1, "书签列表返回 1 条")

b = R.add_bookmark(KEY, cfi="epubcfi(/6/4)", href="chap1.xhtml", excerpt="羞耻感是一种深层情绪")
chk(b["ok"] and b["item"]["id"] == bid, "同位置重复添加幂等（id 不变）")
chk(len(R.bookmarks_of(KEY)) == 1, "幂等不产生副本")

chk(R.remove_bookmark(KEY, bid), "软删除成功")
chk(len(R.bookmarks_of(KEY)) == 0, "删除后列表为空")
chk(len(R.load_bookmarks().get(KEY) or []) == 1, "软删除：数据仍在文件里")

a2 = R.add_bookmark(KEY, cfi="epubcfi(/6/4)", href="chap1.xhtml", excerpt="羞耻感是一种深层情绪")
chk(a2["ok"] and a2["item"]["id"] == bid, "重新添加同位置 -> 恢复原书签")
chk(len(R.bookmarks_of(KEY)) == 1, "恢复后列表可见")

chk(not R.add_bookmark("BAD", cfi="x")["ok"], "非法 key 被拒绝")
chk(not R.add_bookmark(KEY, cfi="", href="")["ok"], "无定位信息被拒绝")

# 损坏 JSON 容错
with open(R.BOOKMARK_PATH, "w", encoding="utf-8") as f:
    f.write("{ not json")
chk(R.bookmarks_of(KEY) == [], "损坏的 JSON 降级为空，不抛异常")

section("HTTP 冒烟 · 新路由返回正确 JSON")
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
import app

s = __import__("socket").socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
httpd = ThreadingHTTPServer(("127.0.0.1", PORT), app.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"


def _read(resp):
    return resp.status, json.loads(resp.read().decode("utf-8"))


def get_json(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return _read(resp)
    except urllib.error.HTTPError as e:
        return _read(e)


def post_json(path, body, origin=True):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = BASE
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return _read(resp)
    except urllib.error.HTTPError as e:
        return _read(e)


chk(get_json("/api/reader/search?key=bad&q=test")[1].get("ok") is False,
    "search 非法 key -> ok:false")
# 把测试 EPUB 注册进阅读器的 key 索引，让 resolve_path 能解析
REAL_KEY = "c" * 16
R._INDEX[REAL_KEY] = EPUB
st, data = get_json("/api/reader/search?key=" + REAL_KEY + "&q=%E7%BE%9E%E8%80%BB")
chk(st == 200 and "hits" in data, "search 路由返回 200 + hits")
st, data = post_json("/api/reader/bookmarks", {"action": "add", "key": "BAD", "cfi": "x"})
chk(data.get("ok") is False, "bookmarks 非法 key -> ok:false")

# 跨站请求 -> 403
req = urllib.request.Request(BASE + "/api/reader/bookmarks",
                             data=json.dumps({"action": "add", "key": KEY, "cfi": "x"}).encode(),
                             headers={"Content-Type": "application/json", "Origin": "http://evil.com"},
                             method="POST")
try:
    urllib.request.urlopen(req, timeout=10)
    chk(False, "bookmarks 跨站请求被 403")
except urllib.error.HTTPError as e:
    chk(e.code == 403, "bookmarks 跨站请求被 403")

st, data = post_json("/api/reader/bookmarks", {"action": "remove", "key": KEY, "id": "nonexistent"})
chk(st == 200 and data.get("ok") is False, "bookmarks remove 不存在 -> ok:false")

httpd.shutdown()

print(f"\n结果：{ok} 通过 / {fail} 失败")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fail else 0)
