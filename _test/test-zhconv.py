# -*- coding: utf-8 -*-
"""简繁双向转换 + 文件级转换 + HTTP 接口 的回归测试。

覆盖新增能力（test-hanzi.py 只测了 繁→简）：
  · to_traditional（简→繁）的正确性，重点是一简对多繁的消歧；
  · detect() / convert(auto) 自动判别；
  · epub.convert_epub 双向 + 结构保护；
  · zhconv_file 对 EPUB / TXT（GBK / UTF-8）的转换；
  · HTTP 接口 /api/zh-convert 端到端（上传→转换→下载→元信息）。
"""
from __future__ import annotations

import base64
import io
import json
import os
import struct
import sys
import tempfile
import threading
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import app as APP                                          # noqa: E402
from kindle import epub as E                               # noqa: E402
from kindle import hanzi as H                              # noqa: E402
from kindle import zhconv_file as Z                        # noqa: E402

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


TMP = tempfile.mkdtemp(prefix="kb-zhconv-")


def write_epub(path, title="红楼梦", body_trad=False):
    """造一份 EPUB，繁体/简体可选，正文里埋 style 与 script 验证结构保护。"""
    t1 = title if body_trad else title
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
        'unique-identifier="bid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f"    <dc:title>{t1}</dc:title>\n"
        '    <dc:creator>曹雪芹</dc:creator>\n'
        '    <dc:language>zh-CN</dc:language>\n'
        '  </metadata>\n'
        '  <manifest><item id="ncx" href="toc.ncx" '
        'media-type="application/x-dtbncx+xml"/>'
        '<item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/></manifest>\n'
        '  <spine toc="ncx"><itemref idref="c1"/></spine>\n'
        "</package>"
    )
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles>\n'
        "</container>"
    )
    if body_trad:
        chap = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>第一回</title>\n'
            '<style type="text/css">.a{font-family:"標楷體"}</style></head>\n'
            "<body><h1>甄士隱</h1>\n"
            "<p>頭髮與發展，皇后與後宮，乾淨與乾燥，公里里程。</p>\n"
            '<script>var s="這是腳本";</script>\n'
            "</body></html>"
        )
    else:
        chap = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>第一回</title>\n'
            '<style type="text/css">.a{font-family:"标楷体"}</style></head>\n'
            "<body><h1>甄士隐</h1>\n"
            "<p>头发与发展，皇后与后宫，干净与干燥，公里里程。</p>\n"
            '<script>var s="这是脚本";</script>\n'
            "</body></html>"
        )
    ncx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">\n'
           f'<docTitle><text>{t1}</text></docTitle></ncx>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo("mimetype", (1980, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, b"application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/chap1.xhtml", chap)
        z.writestr("OEBPS/toc.ncx", ncx)
    return path


# ==================================================== A. 简→繁 正确性
section("A. 简→繁 转换正确性（一简对多繁消歧）")

chk(H.available(), "数据表可用")
chk(H.backend() == "opencc", f"转换内核应为开源 OpenCC（实际：{H.backend()}）")
chk(H.to_traditional("头发") == "頭髮", "头发 → 頭髮（不是「头發」）")
chk(H.to_traditional("发展") == "發展", "发展 → 發展（不是「髮展」）")
chk(H.to_traditional("干净") == "乾淨", "干净 → 乾淨")
chk(H.to_traditional("里面") == "裡面", "里面 → 裡面（不是「裏面」也行，但须是裡语境）")
chk(H.to_traditional("公里") == "公里", "公里 不误转成 公裡（单元音里程保留）")
chk(H.to_traditional("里程") == "里程", "里程 不误转")
chk(H.to_traditional("皇后") == "皇后", "皇后 不误转成 皇後")
chk(H.to_traditional("太后") == "太后", "太后 不误转成 太後")
chk(H.to_traditional("历史") == "歷史", "历史 → 歷史")
chk(H.to_traditional("日历") == "日曆", "日历 → 日曆")
chk(H.to_traditional("我们在这里读书") == "我們在這裡讀書", "整句简→繁")
chk(H.to_traditional("Pride and Prejudice") == "Pride and Prejudice", "英文原样不动")

# OpenCC 完整性：旧自制表漏转的古典小说冷僻对应，现在应全覆盖
_chk_full = H.to_simplified("捲擡舖逕牀啟盃煙麵")
chk("捲擡舖逕牀啟盃煙麵" not in _chk_full and
    all(c in _chk_full for c in "卷抬铺迳床启杯烟面"),
    f"OpenCC 覆盖冷僻繁体（捲擡舖逕牀啟盃煙麵→{_chk_full}）")
# 须保留的词：乾坤/乾红 的「乾」不能转成「干」（干坤是错的）
chk(H.to_simplified("乾坤再造之恩") == "乾坤再造之恩",
    "乾坤 的「乾」须保留（不误转成 干）")
chk(H.to_simplified("拜谢乾坤") == "拜谢乾坤", "乾坤 保留（语料回归）")
# 变徵：五声音阶「宫商角徵羽」的徵(zhǐ)不是「征」，不能一刀切
chk(H.to_simplified("變徵之聲") == "变徵之声",
    f"變徵 保留「徵」（实际 {H.to_simplified('變徵之聲')}）")
chk(H.to_simplified("宫商角徵羽") == "宫商角徵羽", "宫商角徵羽 不被误转")
# 薴：OpenCC 只做第一跳 薴→苧，苧→苎 这一跳断了，补丁要接上
chk(H.to_simplified("薴") == "苎", f"薴 → 苎（链式补全，实际 {H.to_simplified('薴')}）")

# ==================================================== B. 自动判别
section("B. detect / convert(auto)")

chk(H.detect("這是一本繁體書") == "traditional", "detect 繁体")
chk(H.detect("这是一本简体书") == "simplified", "detect 简体")
chk(H.detect("Hello world") == "unknown", "detect 无中文 → unknown")
chk(H.convert("頭髮與發展", "auto") == "头发与发展", "auto：繁→简")
chk(H.convert("头发与发展", "auto") == "頭髮與發展", "auto：简→繁")
chk(H.convert("这是简体书", "traditional") == "這是簡體書", "显式繁体方向")
chk(H.convert("這是繁體書", "simplified") == "这是繁体书", "显式简体方向")

# ==================================================== C. EPUB 双向
section("C. EPUB 转换双向 + 结构保护")

src_t = write_epub(os.path.join(TMP, "trad.epub"), title="紅樓夢", body_trad=True)
out_s = os.path.join(TMP, "trad_s.epub")
r = Z.zhconv_file(src_t, out_s, "simplified")
chk(r["ok"] and r["title_after"] == "红楼梦", f"繁体EPUB→简体，书名 {r.get('title_before')}→{r.get('title_after')}")
with zipfile.ZipFile(out_s) as z:
    chap = z.read("OEBPS/chap1.xhtml").decode("utf-8")
    chk("头发与发展，皇后与后宫，干净与干燥，公里里程。" in chap, "正文已转简体且一简对多没弄错")
    chk('.a{font-family:"標楷體"}' in chap, "style 内繁体被保护")
    chk('var s="這是腳本";' in chap, "script 内繁体被保护")
rep = E.inspect_epub(out_s)
chk(rep["valid"] and not rep["issues"], "产出通过 EPUB 体检")

src_s = write_epub(os.path.join(TMP, "simp.epub"), title="红楼梦", body_trad=False)
out_t = os.path.join(TMP, "simp_t.epub")
r2 = Z.zhconv_file(src_s, out_t, "traditional")
chk(r2["ok"] and r2["title_after"] == "紅樓夢", f"简体EPUB→繁体，书名 {r2.get('title_before')}→{r2.get('title_after')}")
with zipfile.ZipFile(out_t) as z:
    chap = z.read("OEBPS/chap1.xhtml").decode("utf-8")
    chk("頭髮與發展，皇后與後宮，乾淨與乾燥，公里里程。" in chap, "正文已转繁体且消歧正确")
    chk('var s="这是脚本";' in chap, "script 块受保护，保持原样不被转换")
rep2 = E.inspect_epub(out_t)
chk(rep2["valid"] and not rep2["issues"], "产出通过 EPUB 体检")

# ==================================================== D. TXT 文件级（编码嗅探）
section("D. TXT 文件级转换（GBK / UTF-8）")

txt_gbk = os.path.join(TMP, "a.txt")
with open(txt_gbk, "w", encoding="gb18030") as f:
    f.write("我们在这里读书，头发干净，里面有人，公里里程，历史悠长。")
out_gbk = os.path.join(TMP, "a_t.txt")
rg = Z.zhconv_file(txt_gbk, out_gbk, "traditional")
chk(rg["ok"] and rg["encoding"] == "gb18030", f"GBK 编码被嗅探到：{rg.get('encoding')}")
with open(out_gbk, encoding="utf-8") as f:
    body = f.read()
chk(body == "我們在這裡讀書，頭髮乾淨，裡面有人，公里里程，歷史悠長。",
    "GBK 简→繁 正确（含 头发→頭髮、里面→裡面、公里保留）")

txt_utf = os.path.join(TMP, "b.txt")
with open(txt_utf, "w", encoding="utf-8") as f:
    f.write("我們在這裡讀書，頭髮乾淨，裡面有人，公里里程，歷史悠長。")
out_utf = os.path.join(TMP, "b_s.txt")
ru = Z.zhconv_file(txt_utf, out_utf, "auto")
chk(ru["ok"] and ru["direction"] == "自动", f"UTF-8 繁→简 auto：{ru.get('direction')}")
with open(out_utf, encoding="utf-8") as f:
    chk(f.read() == "我们在这里读书，头发干净，里面有人，公里里程，历史悠长。", "UTF-8 繁→简 正确")

# 不支持的格式应被拒绝
bad = os.path.join(TMP, "x.pdf")
open(bad, "wb").write(b"%PDF-1.4")
rb = Z.zhconv_file(bad, os.path.join(TMP, "x2.pdf"), "auto")
chk(not rb["ok"] and "不支持" in rb.get("error", ""), "非 EPUB/TXT 被拒绝")

# ==================================================== E. HTTP 接口端到端
section("E. HTTP /api/zh-convert 端到端")


def start_server():
    srv = APP.ThreadingHTTPServer(("127.0.0.1", 0), APP.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


srv = start_server()
PORT = srv.server_address[1]
BASE = f"http://127.0.0.1:{PORT}"


def post_file(path, direction, inbox="0"):
    with open(path, "rb") as f:
        blob = f.read()
    req = urllib.request.Request(
        BASE + "/api/zh-convert", data=blob, method="POST",
        headers={
            "X-Filename": base64.urlsafe_b64encode(
                os.path.basename(path).encode()).decode(),
            "X-Direction": direction,
            "X-Inbox": inbox,
        })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read(), resp.headers


# E1. 上传简体 TXT → 繁体下载
up = os.path.join(TMP, "up.txt")
with open(up, "w", encoding="utf-8") as f:
    f.write("我们在这里读书，头发干净，里面有人。")
body, headers = post_file(up, "traditional")
meta = json.loads(base64.urlsafe_b64decode(headers.get("X-Zh-Meta")))
chk(body.decode("utf-8") == "我們在這裡讀書，頭髮乾淨，裡面有人。",
    f"接口返回已转繁体：{body.decode('utf-8')}")
chk(meta.get("direction") == "繁体", f"接口元信息方向：{meta.get('direction')}")

# E2. 上传繁体 EPUB → 简体下载，且结构合法
body2, headers2 = post_file(src_t, "simplified")
meta2 = json.loads(base64.urlsafe_b64decode(headers2.get("X-Zh-Meta")))
chk(meta2.get("title_after") == "红楼梦", f"接口 EPUB 书名转简体：{meta2.get('title_after')}")
tmp_ep = os.path.join(TMP, "via_http.epub")
with open(tmp_ep, "wb") as f:
    f.write(body2)
rep3 = E.inspect_epub(tmp_ep)
chk(rep3["valid"] and not rep3["issues"], "接口返回的 EPUB 通过体检")

# E3. X-Inbox=1 同时落「收书」
inbox_dir = APP.INBOX_DIR
os.makedirs(inbox_dir, exist_ok=True)
before = set(os.listdir(inbox_dir))
post_file(up, "traditional", "1")
after = set(os.listdir(inbox_dir))
new_files = after - before
chk(any(n.endswith(".txt") for n in new_files), f"X-Inbox=1 已写入收书：{new_files}")

srv.shutdown()

# ---------------------------------------------------------------- 收尾
print(f"\n{'=' * 46}")
print(f"通过 {ok} 项，失败 {fail} 项")
sys.exit(1 if fail else 0)
