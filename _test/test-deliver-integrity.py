# -*- coding: utf-8 -*-
"""投递去重 + 完整性测试：全程用本地临时目录，不碰真设备。

分成几组：

  去重组（A）—— 证明「同一本书换个名字照样认出来」，以及「不同内容绝不互相覆盖」。
  完整性组（B）—— 证明坏文件进不了设备：源坏了拦在前面，复制坏了拦在中间。
  空间组（C）  —— 放不下就提前说，别拷一半才失败。
  产物组（D）  —— 转码/整理出来的东西，产出后必须再体检一遍。

真实设备相关的坑（拔线、写满）用 monkeypatch 模拟，不真去拔任何东西。
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from kindle import deliver as D                          # noqa: E402
from kindle import integrity as I                        # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "test_mobi_helper", os.path.join(HERE, "test-mobi.py"))
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
build_mobi = _m.build_mobi

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


TMP = tempfile.mkdtemp(prefix="kb-deliver-")


def sub(name: str) -> str:
    p = os.path.join(TMP, name)
    os.makedirs(p, exist_ok=True)
    return p


def write_mobi(path: str, title: str, author: str = "某作者", **kw) -> str:
    """build_mobi 返回的是字节，这里负责落盘。"""
    blob = build_mobi(title, author, name_field="TESTBOOK", **kw)
    with open(path, "wb") as f:
        f.write(blob)
    return path


def write_epub(path: str, title: str = "测试书") -> str:
    """拼一份结构合规的 EPUB。"""
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title><dc:language>zh-CN</dc:language>
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
    chap = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            "<head><title>一</title></head><body><p>正文内容。</p></body></html>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo("mimetype", (1980, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, b"application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/chap1.xhtml", chap)
        z.writestr("OEBPS/toc.ncx",
                   '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"/>')
    return path


# ============================================================ A. 去重
section("A. 去重：内容相同就该认出来，不管叫什么名字")

docs = sub("documents")
src = sub("src")
alt = sub("src-alt")            # 另一个来源目录，用来造「同名但不同内容」

book_a = write_mobi(os.path.join(src, "a.mobi"), "红楼梦")
book_a2 = shutil.copy(book_a, os.path.join(src, "曹雪芹 - 红楼梦.mobi"))
chk(I.same_content(book_a, book_a2), "same_content 认出两份字节完全相同的文件")

steps = D.push_native([book_a], docs, sub("fallback1"))
chk(steps[0].ok and os.path.isfile(os.path.join(docs, "a.mobi")),
    f"第一本正常进设备：{steps[0].message}")

before = sorted(os.listdir(docs))
steps = D.push_native([book_a2], docs, sub("fallback1"))
after = sorted(os.listdir(docs))
chk(before == after, f"换个名字再投一次，设备里没有多出文件（{steps[0].message}）")
chk("已经有这本了" in steps[0].message, "提示语明确说明是重复跳过，而不是静默失败")
chk(steps[0].out.endswith("a.mobi"), "跳过时把设备上已有的那本指出来，方便核对")

section("A2. 内容不同就不能互相覆盖")

book_other = write_mobi(os.path.join(alt, "a.mobi"), "石头记")
chk(not I.same_content(book_a, book_other), "same_content 区分开两份内容不同的文件")
original_bytes = open(os.path.join(docs, "a.mobi"), "rb").read()

steps = D.push_native([book_other], docs, sub("fallback1"))
chk(steps[0].ok, f"同名不同内容时照样投递成功：{steps[0].message}")
chk(os.path.basename(steps[0].out) == "a (2).mobi",
    f"落点为「a (2).mobi」，没有覆盖原有的 a.mobi（实际：{os.path.basename(steps[0].out)}）")
chk(open(os.path.join(docs, "a.mobi"), "rb").read() == original_bytes,
    "设备上原有的 a.mobi 字节未变，没有被悄悄替换")

section("A3. 同一批次内的重复 & 子目录里的书")

docs2 = sub("documents2")
steps = D.push_native([book_a, book_a2], docs2, sub("fallback2"))
chk(len(steps) == 2 and steps[1].ok and "已经有这本了" in steps[1].message,
    "同一批次里投两本相同的，第二本被识别为重复")
chk(len([f for f in os.listdir(docs2) if f.endswith(".mobi")]) == 1,
    "设备里最终只有一本，没出现「(2)」副本")

docs3 = sub("documents3")
nested = os.path.join(docs3, "曹雪芹")
os.makedirs(nested, exist_ok=True)
shutil.copy(book_a, os.path.join(nested, "红楼梦.mobi"))
steps = D.push_native([book_a2], docs3, sub("fallback3"))
chk(steps[0].ok and "已经有这本了" in steps[0].message,
    f"藏在子目录里的同一本书也能被认出来（{steps[0].message}）")

# ============================================================ B. 完整性
section("B. 复制完整性：写完必须当场验货")

docs4 = sub("documents4")
steps = D.push_native([book_a], docs4, sub("fallback4"))
target = steps[0].out
chk(steps[0].ok and I.same_content(book_a, target),
    "投递后设备上的文件与源文件逐字节一致")
chk("结构正常" in steps[0].message,
    f"投递后额外做了结构复检：{steps[0].message}")
chk(not any(f.endswith(".kbtmp") for f in os.listdir(docs4)),
    "正常投递后没有残留 .kbtmp 临时文件")

section("B2. 复制被截断时：拦下，且不留残骸")

docs5 = sub("documents5")
orig_sync = I._sync_copy


def _truncated_sync(src: str, tmp: str) -> None:
    """模拟拷到一半拔线：只落了前 100 字节。"""
    with open(src, "rb") as f, open(tmp, "wb") as o:
        o.write(f.read()[:100])


I._sync_copy = _truncated_sync
try:
    steps = D.push_native([book_a], docs5, sub("fallback5"))
finally:
    I._sync_copy = orig_sync

chk(not steps[0].ok, f"复制被截断时判定为失败：{steps[0].message}")
chk("校验" in steps[0].message, "失败原因说清楚是校验没过，不是含糊的「复制失败」")
chk(not any(f.endswith(".mobi") for f in os.listdir(docs5)),
    "损坏的文件没有留在设备上（已当场撤下）")
chk(not any(f.endswith(".kbtmp") for f in os.listdir(docs5)),
    "临时文件也清理干净了")

section("B3. 源文件本身就是坏的：拦在送进设备之前")

docs6 = sub("documents6")
broken = os.path.join(src, "broken.mobi")
with open(broken, "wb") as f:
    f.write(build_mobi("坏书", "某人", name_field="BADBOOK", truncate=200))
found = D._hard_issues(D.inspect_any(broken))
chk(bool(found), f"截断的文件被体检器判为有问题：{found[0]['msg'] if found else '（未识别）'}")
steps = D.push_native([broken], docs6, sub("fallback6"))
chk(not steps[0].ok and "不往设备里送" in steps[0].message,
    f"坏文件根本没被复制：{steps[0].message}")
chk(not any(f.endswith(".mobi") for f in os.listdir(docs6)),
    "设备目录保持干净")

# ============================================================ C. 空间预检
section("C. 空间预检：放不下就提前说，别拷一半才失败")

docs7 = sub("documents7")
orig_free = I.free_bytes
I.free_bytes = lambda p: 1024 * 1024          # 只剩 1 MB
try:
    steps = D.push_native([book_a], docs7, sub("fallback7"))
finally:
    I.free_bytes = orig_free

chk(not steps[0].ok and "空间不足" in steps[0].message,
    f"空间不够时被拦下：{steps[0].message}")
chk(not any(f.endswith(".mobi") for f in os.listdir(docs7)),
    "没有写出半截文件")

# ============================================================ D. 产物回读
section("D. 整理产物：产出后必须再体检一遍")

src2 = sub("src2")
good_epub = write_epub(os.path.join(src2, "good.epub"), "一本好书")
out_dir = sub("out-clean")
steps = D.clean_epubs([good_epub], out_dir)
chk(steps[0].ok and "结构复检通过" in steps[0].message,
    f"整理 EPUB 后回读通过：{steps[0].message}")
chk(os.path.isfile(steps[0].out), "产物确实落盘了")

section("D2. EPUB 走 MOBI 通道必须被拒")

docs8 = sub("documents8")
steps = D.push_native([good_epub], docs8, sub("fallback8"))
chk(not steps[0].ok and "EPUB" in steps[0].message,
    f"EPUB 不会被当成原生格式塞进设备：{steps[0].message}")

section("D3. push_to_device 不再静默覆盖")

docs9 = sub("documents9")
shutil.copy(book_a, os.path.join(docs9, "同名.mobi"))
kept = open(os.path.join(docs9, "同名.mobi"), "rb").read()

steps = D.push_to_device([book_a], docs9)
chk(steps[0].ok and "已经有这本了" in steps[0].message,
    f"设备上已有相同内容时跳过，不重复写：{steps[0].message}")
chk(open(os.path.join(docs9, "同名.mobi"), "rb").read() == kept,
    "原有文件没被重写（字节保持原样）")

# 同名，但内容是另一本书 —— 这才是真正的撞名场景
collide = os.path.join(alt, "同名.mobi")
shutil.copy(book_other, collide)
steps = D.push_to_device([collide], docs9)
chk(steps[0].ok and os.path.basename(steps[0].out) == "同名 (2).mobi",
    f"另一本书同名时另起名字，不覆盖：{os.path.basename(steps[0].out)}")
chk(open(os.path.join(docs9, "同名.mobi"), "rb").read() == kept,
    "原来的那本书完好无损")
chk(I.same_content(book_other, steps[0].out), "新落地的那本内容正确")

# ============================================================ E. 索引本身
section("E. 设备索引")

idx = D.DeviceIndex(docs9).build()
chk(idx.ready and len(idx.paths) == 2, f"索引建起来，扫到 {len(idx.paths)} 本书")
chk(idx.find_duplicate(book_a) != "", "能从索引里查回已存在的书")
chk(idx.find_duplicate(book_other) != "", "第二本也在索引里")
ghost = write_mobi(os.path.join(src, "ghost.mobi"), "一本从没投过的书")
chk(idx.find_duplicate(ghost) == "", "没投过的书查不到，不会误判为重复")
chk(D.DeviceIndex("").build().ready is False, "没连设备时索引为空，不会误报")

# ---------------------------------------------------------------- 收尾
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'=' * 46}")
print(f"通过 {ok} 项，失败 {fail} 项")
sys.exit(1 if fail else 0)
