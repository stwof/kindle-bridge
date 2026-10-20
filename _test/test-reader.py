# -*- coding: utf-8 -*-
"""本地阅读器后端测试：书架、元信息/封面、TXT 打包、进度标注、key 安全。

做法：把 reader 模块内的路径常量改指向临时目录，全程不碰用户真的「收书/」，
也不连 Kindle（find_kindle 直接打成 None）。MOBI→EPUB 那组需要本机有 Calibre，
没有就自动跳过。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from kindle import reader as R                                     # noqa: E402
from kindle import epub as EEPUB                                   # noqa: E402
from kindle import convert as CONV                                 # noqa: E402

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


# ---------------------------------------------------------------------------
# 把模块路径全部改到临时目录
# ---------------------------------------------------------------------------
TMP = tempfile.mkdtemp(prefix="kb-reader-")
R._DATA = TMP
R.SHELF_DIR = os.path.join(TMP, "书架")
R.PROGRESS_PATH = os.path.join(R.SHELF_DIR, "进度.json")
R.ANNOT_PATH = os.path.join(R.SHELF_DIR, "标注.json")
R._BOOKS_CACHE = os.path.join(TMP, "工具", "缓存", "阅读器", "书籍")
R._COVERS_CACHE = os.path.join(TMP, "工具", "缓存", "阅读器", "封面")
R.dev_mod.find_kindle = lambda: None          # 测试不读设备

INBOX = os.path.join(TMP, "收书")
os.makedirs(INBOX, exist_ok=True)

JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300ffd9")


def make_epub(path: str, title: str = "围城", author: str = "钱钟书",
              cover_href: str = "OEBPS/images/cover.jpg") -> str:
    """造一份最小但合规的 EPUB 2.0（带封面，走 EPUB2 的 <meta name="cover">）。"""
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>
    <dc:language>zh-CN</dc:language>
    <meta name="cover" content="coverimg"/>
  </metadata>
  <manifest>
    <item id="coverimg" href="images/cover.jpg" media-type="image/jpeg"/>
    <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""
    cont = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
             media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    chap = ("<?xml version='1.0' encoding='UTF-8'?>"
            "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>正文。</p></body></html>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo("mimetype")
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, b"application/epub+zip")
        z.writestr("META-INF/container.xml", cont)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/chap1.xhtml", chap)
        if cover_href:
            z.writestr(cover_href, JPEG)
    return path


EPUB1 = make_epub(os.path.join(INBOX, "围城.epub"))
EPUB2 = make_epub(os.path.join(INBOX, "无封面.epub"), title="", author="",
                  cover_href="")

# ---------------------------------------------------------------------------
section("EPUB 元信息与封面")
m = R.meta(EPUB1)
chk(m["title"] == "围城" and m["author"] == "钱钟书", "书名/作者从 OPF 读出来")
chk(m["drm"] is False, "无 DRM")

cov = R.cover_bytes(EPUB1)
chk(bool(cov) and cov[0] == JPEG and cov[1] == ".jpg", "封面字节抽对了（EPUB2 meta name=cover）")

k1 = R.key_for(EPUB1)
hit = R.cover_cached(EPUB1, k1)
chk(bool(hit) and os.path.isfile(hit[0]) and hit[1] == "image/jpeg",
    "封面落盘缓存，返回 (路径, content-type)")
hit2 = R.cover_cached(EPUB1, k1)
chk(hit2 and hit2[0] == hit[0], "再次取封面命中同一份缓存")

m2 = R.meta(EPUB2)
chk(m2["title"] == os.path.splitext(os.path.basename(EPUB2))[0],
    "没书名时退回文件名")
chk(R.cover_bytes(EPUB2) is None, "没有封面时返回 None 而不是抛错")

# ---------------------------------------------------------------------------
section("书架扫描")
TXT = os.path.join(INBOX, "浮生六记.txt")
with open(TXT, "w", encoding="utf-8") as f:
    f.write("浮生六记\n作者：沈复\n\n" + "闺房记乐，世事茫茫。\n\n" * 400)

shelf = R.scan_shelf()
by_key = {b["key"]: b for b in shelf}
chk(len(shelf) == 3, f"扫到 3 本书（实际 {len(shelf)}）")
b1 = by_key.get(R.key_for(EPUB1))
chk(bool(b1) and b1["kind"] == "epub" and b1["source"] == "收书"
    and b1["needs_convert"] is False and b1["title"] == "围城", "EPUB 书卡字段正确")
b3 = by_key.get(R.key_for(TXT))
chk(bool(b3) and b3["kind"] == "txt" and b3["needs_convert"] is True
    and b3["title"] == "浮生六记", "TXT 书卡字段正确（现场打包）")

# ---------------------------------------------------------------------------
section("key → 路径：拒绝一切非法输入")
chk(R.resolve_path(R.key_for(EPUB1)) == EPUB1, "合法 key 能解析回路径")
for bad in ["", "..", "../x", "zzzz", "a" * 15, "A" * 16, "a" * 17,
            "0" * 15 + "g", "../../etc/passwd", "null"]:
    if R.resolve_path(bad) is not None:
        chk(False, f"拒绝非法 key：{bad!r}")
        break
else:
    chk(True, "非法 key（含路径穿越、非十六进制、长度不对）一律拒绝")

# ---------------------------------------------------------------------------
section("TXT → EPUB（本地打包，不依赖 Calibre）")
r = R.ensure_readable(TXT)
chk(r.get("ok") and os.path.isfile(r["path"]), "TXT 能变成 EPUB")
chk(r.get("encoding") == "utf-8", "编码识别为 utf-8")
rep = EEPUB.inspect_epub(r["path"])
chk(rep["valid"] and rep["title"] == "浮生六记",
    f"产物合法且书名不乱码（title={rep['title']!r}）")
chk(rep["spine"] >= 2, f"长文本分章（spine={rep['spine']}）")

# GBK 的 txt 也要认（windows 上很常见）
GBK = os.path.join(INBOX, "gbk书.txt")
with open(GBK, "w", encoding="gb18030") as f:
    f.write("天方夜谭\n\n" + "很久很久以前，有一个故事。\n\n" * 60)
rg = R.ensure_readable(GBK)
chk(rg.get("ok") and rg.get("encoding") == "gb18030", "GBK txt 识别为 gb18030")
chk(EEPUB.inspect_epub(rg["path"])["title"] == "天方夜谭", "GBK txt 书名不乱码")

# 空文件 / 超大文件要给错误而不是崩
EMPTY = os.path.join(INBOX, "空的.txt")
open(EMPTY, "wb").write(b"")
chk(not R.ensure_readable(EMPTY).get("ok"), "空 txt 明确报错")

# ---------------------------------------------------------------------------
section("EPUB 直接用，不重复“转换”")
r = R.ensure_readable(EPUB1)
chk(r.get("ok") and r.get("converted") is False and r["path"] == EPUB1,
    "EPUB 原样返回（不制造副本）")

# ---------------------------------------------------------------------------
section("MOBI 家族 → EPUB（外调 Calibre，需本机装有）")
if CONV.find_ebook_convert():
    mobi = os.path.join(INBOX, "测试.mobi")
    # 借一份真 azw3 的结构太啰嗦，这里拿不到真 mobi 就造个假的：
    # 直接用 Calibre 把 EPUB 转成 AZW3，再转回 EPUB —— 走完整条链路
    import subprocess
    azw3 = os.path.join(INBOX, "测试.azw3")
    conv = CONV.find_ebook_convert()
    cflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    pr = subprocess.run([conv, EPUB1, azw3], capture_output=True, timeout=300,
                        creationflags=cflags)
    if os.path.isfile(azw3):
        k = R.key_for(azw3)
        chk(R.resolve_path(k) == azw3, "AZW3 进书架")
        rr = R.ensure_readable(azw3)
        chk(rr.get("ok") and rr.get("converted"), "AZW3 交给 Calibre 转成 EPUB")
        if rr.get("ok"):
            rep = EEPUB.inspect_epub(rr["path"])
            chk(rep["valid"] and rep["title"] == "围城", f"转出的 EPUB 合法（title={rep['title']!r}）")
            t0 = os.path.getmtime(rr["path"])
            rr2 = R.ensure_readable(azw3)
            chk(rr2.get("ok") and rr2.get("cached") is True, "第二次命中缓存")
        os.remove(azw3)
    else:
        chk(False, "Calibre 未能生成测试用 AZW3（环境限制，跳过转换断言）")
else:
    print("  [SKIP] 本机没有 Calibre，跳过 MOBI→EPUB 断言")

# ---------------------------------------------------------------------------
section("阅读进度 / 标注")
CK = R.key_for(EPUB1)
chk(R.save_progress("bad", 10).get("ok") is False, "非法 key 拒绝写进度")
chk(R.save_progress(CK, 0.25, "epubcfi(/2/4)", "第一章").get("ok"), "保存进度")
pr = R.load_progress().get(CK) or {}
chk(abs(pr.get("percent", 0) - 0.25) < 1e-6 and pr.get("chapter") == "第一章",
    "进度读回来且四舍五入")
chk("at" in pr, "带时间戳")

a1 = R.add_annot(CK, "这是个标注", "epubcfi(/2/4/2)", "", "第一章")
a2 = R.add_annot(CK, "这是个标注", "epubcfi(/2/4/2)", "", "第一章")
chk(a1.get("ok") and a2.get("ok") and a1["item"]["id"] == a2["item"]["id"],
    "同一条标注重复保存不产生重复")
lst = R.annots_of(CK)
chk(len(lst) == 1 and lst[0]["text"] == "这是个标注", "标注列表正确")
chk(R.remove_annot(CK, lst[0]["id"]), "删除标注")
chk(R.annots_of(CK) == [], "删完就空了")
chk(R.remove_annot(CK, "不存在") is False, "删不存在的标注返回 False 而不是崩")

# 空文本 / 空 key 的标注
chk(not R.add_annot(CK, "   ").get("ok"), "空白标注拒绝")
chk(not R.add_annot("bad", "有字").get("ok"), "非法 key 的标注拒绝")

# ---------------------------------------------------------------------------
print(f"\n=== 阅读器测试：{ok} 通过 / {fail} 失败 ===")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fail else 0)
