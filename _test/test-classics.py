# -*- coding: utf-8 -*-
"""中文经典文库（chinese-poetry，MIT 语料）的测试。

语料是外部数据，没下载时整组跳过 —— 跑之前先执行
``python _tools/fetch-chinese-poetry.py``。
"""
from __future__ import annotations

import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kindle import classics as C          # noqa: E402
from kindle import epub as E              # noqa: E402
from kindle import hanzi as H             # noqa: E402

OK: list[str] = []
BAD: list[str] = []


def chk(cond, msg: str) -> None:
    (OK if cond else BAD).append(msg)
    print(("  ok   " if cond else "  FAIL ") + msg)


TMP = tempfile.mkdtemp(prefix="kb-classics-")

if not C.available():
    print("本地中文语料不存在，整组跳过。")
    print("先跑：python _tools/fetch-chinese-poetry.py")
    sys.exit(0)

print("语料目录:", C.CORPUS_DIR)

# ---------------------------------------------------------------- 索引
idx = C.build_index()
books = idx["books"]
chk(len(books) > 50, f"建出书目 {len(books)} 条")

kinds = {}
for b in books:
    kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
print("   书目构成:", kinds)
chk(kinds.get("book", 0) >= 15, f"成册的书 {kinds.get('book', 0)} 本")
chk(kinds.get("merged", 0) >= 1, f"分卷合并的书 {kinds.get('merged', 0)} 本")

# 一条都不能是空的 —— 空书进 Kindle 就是一本打不开的书
empty = [b["title"] for b in books if b["kind"] in ("book", "merged") and not b["works"]]
chk(not empty, f"没有空壳书（空的：{empty[:5]}）")

# ---------------------------------------------------------------- 各种形态
def find(title: str):
    return next((b for b in books if b["title"] == title), None)

cases = [
    # (书名, 期待最少章节数, 说明)
    ("论语", 10, "章节书：{chapter, paragraphs}"),
    ("唐诗三百首", 100, "嵌套书：体裁 → 篇目，不递归就一篇读不到"),
    ("诗经", 100, "正文在 content 数组里，且有章节/小节两级"),
    ("幽梦影", 100, "正文是 content 字符串，且没有标题字段"),
    ("纳兰性德全集", 100, "正文字段叫 para，不是 paragraphs"),
    ("花间集", 100, "分卷书：一个目录 10 个文件合起来才是一本"),
    ("楚辞", 10, "正文在 content 数组里"),
    ("孟子", 5, "四书五经，繁体"),
]
for title, least, why in cases:
    b = find(title)
    if not b:
        chk(False, f"书目里应有《{title}》")
        continue
    _, _, ch = C.chapters_of(b["id"])
    chk(len(ch) >= least, f"《{title}》解析出 {len(ch)} 章（{why}）")

# ---------------------------------------------------------------- 章节标题
b = find("唐诗三百首")
_, _, ch = C.chapters_of(b["id"])
first = ch[0][0]
chk("唐诗三百首" not in first,
    f"章节标题不带书名前缀：「{first}」")
chk("·" in first, f"章节标题保留体裁信息：「{first}」")

# ---------------------------------------------------------------- 朝代
song = [b for b in books if b["kind"] == "author" and b["dynasty"] == "宋"]
tang = [b for b in books if b["kind"] == "author" and b["dynasty"] == "唐"]
chk(len(song) > 0 and len(tang) > 0,
    f"宋诗与唐诗分开标注（宋 {len(song)} 位 / 唐 {len(tang)} 位）")
lu = next((b for b in books if b["author"] in ("陸游", "陆游")), None)
if lu:
    chk(lu["dynasty"] == "宋",
        f"陆游归在宋朝而不是唐朝（按文件名 poet.song.* 判断，实际：{lu['dynasty']}）")
else:
    print("   --   语料里还没有陆游（全唐诗全集未下完），跳过朝代归属检查")

# ---------------------------------------------------------------- 检索
r = C.search("论语", page_size=10)
chk(r["total"] >= 1 and r["items"][0]["title"] == "论语",
    "检索「论语」能精确命中")

# 语料里作者简繁混存（宋词写「陆游」，全唐诗写「陸游」），要统一成一个人才对
for q in ("苏轼", "陆游"):
    rr = C.search(q, page_size=10)
    hit = any(it["author"] == q for it in rr["items"])
    chk(hit, f"检索「{q}」命中 {rr['total']} 条，且作者名已统一为简体")

# 别集作者名必须是简体 —— 繁体混进去就会同一个人变成两本集子
trad = [b["author"] for b in books
        if b["kind"] == "author" and H.is_traditional(b["author"])]
chk(not trad, f"别集作者名无繁体残留（残留 {len(trad)} 个，例：{trad[:3]}）")

# 同一位作者的诗与词要分成两本，而不是混在一本里
lu = [b for b in books if b["kind"] == "author" and b["author"] == "陆游"]
if lu:
    chk(len(lu) >= 1 and all(("诗集" in b["title"]) or ("词集" in b["title"]) for b in lu),
        f"陆游按体裁分集：{'、'.join(b['title'] for b in lu[:3])}")
else:
    print("   --   语料里还没有陆游，跳过分集检查")

rr = C.search("李白 诗", page_size=10)
chk(True, f"多关键词检索「李白 诗」命中 {rr['total']}")

# ---------------------------------------------------------------- 成书
def build_one(title: str, simplified: bool = True):
    b = find(title)
    return C.build_epub(b["id"], TMP, simplified=simplified)

made = build_one("论语")
chk(made.get("ok"), f"《论语》成书成功（{made.get('chapters')} 章 / {made.get('size', 0)} 字节）")

rep = E.inspect_epub(made["out"])
chk(rep["valid"], f"产出的 EPUB 通过体检（问题 {len(rep['issues'])} 条）")
chk(rep["title"] == "论语", f"EPUB 元数据书名正确：{rep['title']}")
chk(rep["spine"] >= 10, f"EPUB 目录里有 {rep['spine']} 个章节")

# 繁体书转简体，正文要真的变成简体
ts = build_one("唐诗三百首")
chk(ts.get("ok"), f"《唐诗三百首》成书成功（{ts.get('chapters')} 章）")
with zipfile.ZipFile(ts["out"]) as z:
    raw = b"".join(z.read(n) for n in z.namelist() if n.endswith(".xhtml")).decode("utf-8")
import re  # noqa: E402
body = re.sub(r"<[^>]+>", "", raw)
ratio = H.ratio_of(body)
chk(ratio < 0.02, f"《唐诗三百首》正文繁体残留 {ratio * 100:.1f}%（应接近 0）")
chk("床前明月光" in body, "正文里能找到「床前明月光」")

# 论语本身就是简体，不该被乱转
with zipfile.ZipFile(made["out"]) as z:
    raw2 = b"".join(z.read(n) for n in z.namelist() if n.endswith(".xhtml")).decode("utf-8")
body2 = re.sub(r"<[^>]+>", "", raw2)
chk("学而时习之" in body2, "本身就是简体的《论语》没被转坏（「学而时习之」仍在）")

# 同一份目录结构要合法：mimetype 必须是第一个且不压缩
with zipfile.ZipFile(ts["out"]) as z:
    names = z.namelist()
    info = z.getinfo("mimetype")
chk(names[0] == "mimetype", "mimetype 是压缩包第一个条目")
chk(info.compress_type == zipfile.ZIP_STORED, "mimetype 未压缩（EPUB 硬性要求）")

# ---------------------------------------------------------------- 边界
b = find("论语")
_, _, ch = C.chapters_of(b["id"])
chk(all(p.strip() for _, ps in ch for p in ps), "没有空白段落混进正文")
chk(all(t.strip() for t, _ in ch), "没有空章节标题")

# 不存在的书必须明确报错，而不是产出一个空壳
try:
    C.build_epub("book:不存在的文件.json", TMP)
    chk(False, "不存在的书应报错")
except KeyError as ex:
    chk(True, f"不存在的书被明确拒绝：{str(ex)[:40]}")

print()
print(f"通过 {len(OK)} 项，失败 {len(BAD)} 项")
if BAD:
    print("失败项：")
    for m in BAD:
        print("   -", m)

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if BAD else 0)
