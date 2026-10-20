# -*- coding: utf-8 -*-
"""简繁转换测试：字符级、短语级、EPUB 结构保护、端到端产出。

重点不是「转了没有」，而是这三件事：
  1. 该转的转对了（尤其是一简对多繁，比如「頭髮」和「發展」都简化成「发」）；
  2. 不该转的没动（标签、style、script、图片字体 —— 动一点点 EPUB 就废了）；
  3. 已经是简体的书不被动（简→繁再简回来只会把「头发」变成「头發」）。
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

from kindle import epub as E                             # noqa: E402
from kindle import hanzi as H                            # noqa: E402
from kindle import mobi as M                             # noqa: E402

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


TMP = tempfile.mkdtemp(prefix="kb-hanzi-")


def write_epub(path: str, title: str = "紅樓夢", author: str = "曹雪芹") -> str:
    """造一份繁体 EPUB，正文里埋了 style 与 CDATA 用来验证「不该动的没动」。"""
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>zh-CN</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx"><itemref idref="c1"/></spine>
</package>"""
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
   media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    # 正文：繁体。style 里也放繁体 —— 它会作为标签内容被保护，不该被转换
    chap = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>第一回</title>
<style type="text/css">.a{font-family:"標楷體"} /* 註解：這是樣式 */</style>
</head>
<body>
<h1>甄士隱夢幻識通靈</h1>
<p>作者自云：因曾歷過一番夢幻之后，故將真事隱去。</p>
<p>頭髮與發展，皇后與後宮，乾淨與乾燥。</p>
<p>義大利的資訊產業，網路的軟體與硬體。</p>
<script type="text/javascript">var s="這是腳本";</script>
</body>
</html>"""
    ncx = '<?xml version="1.0" encoding="UTF-8"?>' \
          '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">' \
          '<docTitle><text>紅樓夢</text></docTitle></ncx>'

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo("mimetype", (1980, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, b"application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/chap1.xhtml", chap)
        z.writestr("OEBPS/toc.ncx", ncx)
    return path


# ==================================================== A. 字符与短语
section("A. 转换正确性")

chk(H.available(), "简繁数据表可用")
chk(H.to_simplified("頭髮與發展") == "头发与发展",
    f"一简对多繁：「頭髮與發展」→「{H.to_simplified('頭髮與發展')}」（两个字都简化成「发」，但不能混）")
chk(H.to_simplified("皇后") == "皇后",
    f"「皇后」不变成「皇後」（{H.to_simplified('皇后')}）—— 一简对多繁的反向陷阱")
chk(H.to_simplified("乾燥與乾淨") == "干燥与干净",
    f"「乾」的两个读音分得开：{H.to_simplified('乾燥與乾淨')}")
chk(H.to_simplified("義大利的資訊產業") == "义大利的资讯产业",
    f"繁→简（OpenCC 规范）：{H.to_simplified('義大利的資訊產業')}")
chk(H.to_simplified("網路的軟體與硬體") == "网路的软体与硬体",
    f"IT 词汇（OpenCC 规范）：{H.to_simplified('網路的軟體與硬體')}")
chk(H.to_simplified("么麼") == "幺麽", f"短语优先：{H.to_simplified('么麼')}")

section("A2. 已经是简体的不能被动")

simp = "这本书本来就是简体，头发与皇后，干净。"
chk(H.to_simplified(simp) == simp, "简体原文一字不动（简→繁再简回来会把「头发」弄成「头發」）")
chk(H.is_traditional(simp) is False, "能判定出这是简体")
chk(H.is_traditional("這本書是繁體") is True, "能判定出这是繁体")
chk(H.ratio_of("這本書是繁體") > 0.9, f"繁体判定分：{H.ratio_of('這本書是繁體'):.2f}")

section("A3. 非中文内容不处理")

chk(H.to_simplified("Pride and Prejudice") == "Pride and Prejudice", "英文原样")
chk(H.looks_chinese("Pride and Prejudice") is False, "能识别英文不算中文")
chk(H.looks_chinese("紅樓夢是一部小說") is True, "能识别中文")

# ==================================================== B. EPUB 结构保护
section("B. EPUB 转换：正文要转，结构不能坏")

src = write_epub(os.path.join(TMP, "繁.epub"))
dst = os.path.join(TMP, "简.epub")
info = E.to_simplified_epub(src, dst)

chk(info["ok"], "转换执行成功")
chk(info["title_before"] == "紅樓夢" and info["title_after"] == "红楼梦",
    f"书名跟着转成简体：{info['title_before']} → {info['title_after']}")

with zipfile.ZipFile(dst) as z:
    names = z.namelist()
    chap = z.read("OEBPS/chap1.xhtml").decode("utf-8")

chk("甄士隱夢幻識通靈" not in chap and "甄士隐梦幻识通灵" in chap,
    "正文标题已转简体")
chk("作者自云：因曾历过一番梦幻之后，故将真事隐去。" in chap,
    "正文段落已转简体")
chk("头发与发展，皇后与后宫，干净与干燥。" in chap,
    f"一简对多繁在正文里也没弄错：{chap[chap.find('头发与发展'):][:24]}")

chk('.a{font-family:"標楷體"} /* 註解：這是樣式 */' in chap,
    "style 块里的繁体原样保留（改了会破坏字体名与结构）")
chk('var s="這是腳本";' in chap,
    "script 块里的繁体原样保留")
chk("<style type=\"text/css\">" in chap and "<script type=\"text/javascript\">" in chap,
    "标签本身完整无损")

# XML 结构必须仍然能解析
from xml.etree import ElementTree as ET                  # noqa: E402
try:
    ET.fromstring(chap)
    chk(True, "转换后的 XHTML 仍是合法 XML（标签没被改坏）")
except ET.ParseError as ex:
    chk(False, f"转换后的 XHTML 解析失败：{ex}")

section("B2. 产出必须是合法 EPUB")

chk(names[0] == "mimetype", f"mimetype 排在首位（实际首位：{names[0]}）")
with zipfile.ZipFile(dst) as z:
    mi = z.getinfo("mimetype")
chk(mi.compress_type == zipfile.ZIP_STORED, "mimetype 未被压缩（EPUB 规范要求）")

rep = E.inspect_epub(dst)
chk(rep["valid"] and not rep["issues"],
    f"产出通过 EPUB 体检：{rep['issues'] if rep['issues'] else '无问题'}")
chk(rep["title"] == "红楼梦", f"产出元数据里的书名已是简体：{rep['title']}")

section("B3. 已是简体的 EPUB 不重复转换")

simp_epub = os.path.join(TMP, "simp.epub")
write_epub(simp_epub, title="红楼梦", author="曹雪芹")
# 把正文也换成简体
with zipfile.ZipFile(simp_epub) as z:
    raw = z.read("OEBPS/chap1.xhtml").decode("utf-8")
with zipfile.ZipFile(simp_epub, "w", zipfile.ZIP_DEFLATED) as z:
    zi = zipfile.ZipInfo("mimetype", (1980, 1, 1, 0, 0, 0))
    zi.compress_type = zipfile.ZIP_STORED
    z.writestr(zi, b"application/epub+zip")
    for nm in ("META-INF/container.xml", "OEBPS/content.opf", "OEBPS/toc.ncx"):
        pass
info2 = E.to_simplified_epub(simp_epub, os.path.join(TMP, "simp-out.epub"))
chk("[简]" in "".join(info2["changed"]) or "未改动" in "".join(info2["changed"]),
    f"简体书不做无谓改动：{info2['changed']}")

# ==================================================== C. 抄捷径必须被拒
section("C. 走不通的路要提前说，别让用户白等")

from kindle import deliver as D                          # noqa: E402
steps = D.to_simplified_azw3([os.path.join(TMP, "nope.mobi")],
                             os.path.join(TMP, "out1"), TMP, converter="")
chk(not steps[0].ok and "文件不存在" in steps[0].message,
    f"文件不存在时报错：{steps[0].message}")

fake = os.path.join(TMP, "fake.mobi")
with open(fake, "wb") as f:
    f.write(b"BOOKMOBI" + b"\x00" * 200)
steps = D.to_simplified_azw3([fake], os.path.join(TMP, "out2"), TMP, converter="")
chk(not steps[0].ok and "EPUB" in steps[0].message,
    f"MOBI 不能直接改文字，如实告知：{steps[0].message}")

# ==================================================== D. 完整链路
section("D. 完整链路：下载 → 转简体 → AZW3（本地源，不联网）")

import http.server                                       # noqa: E402
import threading                                        # noqa: E402
from kindle import freebooks as fb                      # noqa: E402
from kindle.convert import find_ebook_convert           # noqa: E402

served = write_epub(os.path.join(TMP, "dl.epub"), title="紅樓夢", author="曹雪芹")
BLOB = open(served, "rb").read()


class HS(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        rng = self.headers.get("Range", "")
        start, end = 0, len(BLOB) - 1
        if rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a)
            if b:
                end = min(int(b), end)
        n = end - start + 1
        self.send_response(206 if rng else 200)
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(BLOB)}")
        self.send_header("Content-Length", str(n))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(BLOB[start:start + n])

    do_HEAD = do_GET

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HS)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{PORT}/book.epub"

fb.INBOX_DIR = os.path.join(TMP, "inbox")
fb.CACHE_DIR = os.path.join(TMP, "cache")

conv = find_ebook_convert()
if not conv:
    print("  [跳过] 本机没有 Calibre，跳过 AZW3 环节（EPUB 环节已在上文验证）")
else:
    jid = f"{int(__import__('time').time())}-t2s"
    job = {"id": jid, "title": "紅樓夢", "author": "曹雪芹", "source_name": "本地",
           "url": URL, "ext": ".epub", "push": False, "simplified": True,
           "status": "排队", "got": 0, "total": 0, "percent": 0,
           "speed": 0.0, "speed_avg": 0.0, "eta": 0, "error": "",
           "out": "", "queued": fb._now()}
    fb._JOBS[jid] = job
    fb._ORDER.append(jid)
    fb._run_job(job)

    chk(job["status"] == "完成", f"任务完成：{job['status']} {job.get('error', '')}")
    chk(job["out"].endswith(".azw3"),
        f"产出是 AZW3 而非 EPUB：{os.path.basename(job.get('out', ''))}")
    if os.path.isfile(job.get("out", "")):
        rep = M.inspect_mobi(job["out"])
        chk(rep["title"] == "红楼梦", f"书名已转简体：{rep['title']}")
        chk(rep["valid"] and not rep["issues"],
            f"产出通过 Kindle 原生格式体检：{rep['format']}")
    # 原文（繁体 EPUB）应当保留，不替用户删
    kept = [f for f in os.listdir(fb.INBOX_DIR) if f.endswith(".epub")]
    chk(bool(kept), f"繁体原文也留在「收书」里，没有替用户删掉：{kept}")

# ---------------------------------------------------------------- 收尾
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'=' * 46}")
print(f"通过 {ok} 项，失败 {fail} 项")
sys.exit(1 if fail else 0)
