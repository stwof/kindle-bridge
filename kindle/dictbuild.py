# -*- coding: utf-8 -*-
"""阅读字典生成器 —— 把 CC-CEDICT 做成 KOReader 能用的 StarDict 词典。

为什么要这个：上一环给 KOReader 装好了阅读器，但「划词查词」还缺一部字典。
Kindle 桥已经能转简繁，这里再把**查词字典**也补齐 —— 而且一次出两部：
  · 简体字典：词头用简体（读简体书时划词用）
  · 繁體字典：词头用繁体（读繁体公版书时划词用）
两者释义相同（都来自 CC-CEDICT，含拼音与英文/中文释义）。

产物格式是 StarDict（.ifo / .idx / .dict），KOReader 原生支持，拷进
`.adds/koeditor/dicts/` 或 `/mnt/us/extensions/.../dicts/` 即可。

数据来源 CC-CEDICT 是自由许可（CC BY-SA / 公有领域变体均有），不是盗版。
本脚本只负责把这份公开词表打包成字典，**不内置任何版权文本**；词表需联网下载
（或你手动放一份 cedict 文本到本地后指定 --source）。

纯标准库，无第三方依赖。
"""
from __future__ import annotations

import os
import re
import struct
import sys
import zipfile

try:                                    # 源码运行时是包内模块，冻结后是单文件
    from . import paths as _paths
    _DATA_ROOT = _paths.data_dir()
except ImportError:                     # 直接当脚本跑： kindle/dictbuild.py
    _DATA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUT_DEFAULT = os.path.normpath(os.path.join(_DATA_ROOT, "字典"))

# 候选下载源（任一可用即可；GitHub raw 在国内常被墙，多列几个备用）。
# 注意：这些是「尽力而为」的源，若都失效，脚本会教你手动下载后 --source 指定。
CEDICT_SOURCES = [
    "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8.zip",
    "https://github.com/elvisyip/cedict/raw/master/cedict_1_0_ts_utf-8.txt",
    "https://raw.githubusercontent.com/tonytonyjan/cedict/master/cedict_1_0_ts_utf-8.txt",
    "https://ccedict.org/downloads/cedict_1_0_ts_utf-8.zip",
]

_LINE = re.compile(r"^(\S+)\s+(\S+)\s+\[(.*?)\]\s*(.*)$")


def parse_line(line: str):
    """CC-CEDICT 一行：TRAD SIM [拼音] /释义/。返回 (trad, simp, def)，否则 None。"""
    line = line.rstrip("\n")
    if not line or line.startswith("#"):
        return None
    m = _LINE.match(line)
    if not m:
        return None
    trad, simp, pinyin, gloss = m.group(1), m.group(2), m.group(3), m.group(4)
    return trad, simp, "[" + pinyin + "] " + gloss


def _merge(meanings: list[str]) -> bytes:
    """同一词头可能有多条释义，去重后用 ' / ' 拼成一个字符串。"""
    uniq: list[str] = []
    for m in meanings:
        if m not in uniq:
            uniq.append(m)
    return (" / ".join(uniq)).encode("utf-8")


def write_stardict(words: dict[str, list[str]], folder: str, bookname: str) -> dict:
    """把 {词头: [释义...]} 写成 StarDict 三件套（sametypesequence=m）。"""
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r"[^\w一-鿿-]+", "_", bookname)
    dict_path = os.path.join(folder, safe + ".dict")
    idx_path = os.path.join(folder, safe + ".idx")
    ifo_path = os.path.join(folder, safe + ".ifo")

    items = []
    for w, defs in words.items():
        if not w:
            continue
        items.append((w.encode("utf-8"), _merge(defs)))
    # StarDict 要求 .idx 按词头字节序排序（UTF-8 字节序即可）
    items.sort(key=lambda x: x[0])

    offset = 0
    with open(dict_path, "wb") as d, open(idx_path, "wb") as i:
        for w, defb in items:
            d.write(defb)
            i.write(w)
            i.write(b"\x00")
            i.write(struct.pack(">II", offset, len(defb)))
            offset += len(defb)

    ifo = (
        "StarDict's dict ifo file\n"
        "version=2.4.2\n"
        f"bookname={bookname}\n"
        f"wordcount={len(items)}\n"
        f"idxfilesize={os.path.getsize(idx_path)}\n"
        "author=CC-CEDICT (https://ccedict.org)\n"
        "description=由 Kindle 桥生成：CC-CEDICT 中文-英文词典，含拼音与释义。\n"
        "sametypesequence=m\n"
    )
    with open(ifo_path, "w", encoding="utf-8") as f:
        f.write(ifo)

    return {"bookname": bookname, "words": len(items),
            "dict": dict_path, "idx": idx_path, "ifo": ifo_path}


def build_from_txt(txt_path: str, out_dir: str) -> dict:
    simp: dict[str, list[str]] = {}
    trad: dict[str, list[str]] = {}
    with open(txt_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            p = parse_line(line)
            if not p:
                continue
            t, s, d = p
            simp.setdefault(s, []).append(d)
            trad.setdefault(t, []).append(d)
    r1 = write_stardict(simp, os.path.join(out_dir, "简体字典 (CC-CEDICT)"),
                        "CC-CEDICT 简体中文")
    r2 = write_stardict(trad, os.path.join(out_dir, "繁體字典 (CC-CEDICT)"),
                        "CC-CEDICT 繁體中文")
    return {"simplified": r1, "traditional": r2}


def _download(url: str, dest: str) -> bool:
    import shutil
    import ssl
    import urllib.request

    ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KindleBridge/1.0"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            with open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
        return True
    except Exception as ex:  # noqa: BLE001
        print(f"  ✗ 下载失败（{url}）：{ex}")
        return False


def fetch_cedict(cache_dir: str) -> str | None:
    """尝试下载 CC-CEDICT 到 cache_dir，返回解压后 txt 路径；失败返回 None。"""
    os.makedirs(cache_dir, exist_ok=True)
    for url in CEDICT_SOURCES:
        print(f"尝试下载：{url}")
        tmp = os.path.join(cache_dir, "cedict_download")
        if _download(url, tmp):
            # zip 还是 txt？
            if url.endswith(".zip") or open(tmp, "rb").read(4) == b"PK\x03\x04":
                try:
                    with zipfile.ZipFile(tmp) as z:
                        name = next((n for n in z.namelist()
                                     if n.lower().endswith(".txt")), None)
                        if not name:
                            print("  ✗ 压缩包里没有 .txt")
                            continue
                        txt = os.path.join(cache_dir, "cedict.txt")
                        with open(txt, "wb") as f:
                            f.write(z.read(name))
                    return txt
                except zipfile.BadZipFile:
                    print("  ✗ 不是有效 zip")
                    continue
            else:
                txt = os.path.join(cache_dir, "cedict.txt")
                if os.path.exists(tmp):
                    os.replace(tmp, txt)
                return txt
    return None


def write_readme(out_dir: str) -> str:
    readme = os.path.join(out_dir, "README.txt")
    text = (
        "CC-CEDICT 简繁字典（StarDict 格式）\n"
        "====================================\n\n"
        "本文件夹内含两部字典，都是 KOReader 原生支持的 StarDict 格式：\n"
        "  · 简体字典 (CC-CEDICT)/  —— 词头是简体，读简体书时划词查词用\n"
        "  · 繁體字典 (CC-CEDICT)/  —— 词头是繁体，读繁体公版书时划词查词用\n\n"
        "如何装进 KOReader：\n"
        "  1. 用数据线把 Kindle 连上电脑，进入 KOReader 的字典目录，通常是：\n"
        "        KOReader/dicts/\n"
        "     （有的固件在 .adds/koeditor/dicts/ 或 extensions/koreader/dicts/）\n"
        "  2. 把上面两个子文件夹整体拷进去（保留 .ifo/.idx/.dict 三件套在一起）。\n"
        "  3. 在 KOReader 里打开任意书，长按一个词 → 选「字典」即可查词；\n"
        "     在字典列表里可以勾选默认用简体还是繁體字典。\n\n"
        "数据来源与版权：\n"
        "  CC-CEDICT 由马大卫等人维护，采用 Creative Commons 许可，属公开词表，\n"
        "  非盗版、不涉及任何受版权保护的书籍正文。本工具只做格式打包。\n\n"
        "重新生成 / 更新词表：\n"
        "  在本机（需联网）运行：\n"
        "      python kindle/dictbuild.py\n"
        "  若想用自己已有的 cedict 文本，指定路径即可：\n"
        "      python kindle/dictbuild.py --source /path/to/cedict_1_0_ts_utf-8.txt\n"
        "  输出默认在 Kindle 桥根目录下的「字典/」文件夹。\n"
    )
    with open(readme, "w", encoding="utf-8") as f:
        f.write(text)
    return readme


def main():
    import argparse
    ap = argparse.ArgumentParser(description="生成 CC-CEDICT 简繁 StarDict 字典")
    ap.add_argument("--source", help="本地已有的 cedict 文本路径（跳过下载）")
    ap.add_argument("--out", default=OUT_DEFAULT, help="输出目录（默认 Kindle桥/字典）")
    ap.add_argument("--cache", default=os.path.join(BASE_DIR, "data", "cedict_cache"),
                    help="下载缓存目录")
    ap.add_argument("--sample", action="store_true",
                    help="用内置极小样本验证格式（不下载、不联网）")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    if args.sample:
        sample = "# CC-CEDICT sample\n北京 北京 [bei3 jing1] /Beijing/Municipality/\n" \
                 "的確 的确 [di2 que4] /really/truly/\n" \
                 "紅樓夢 红楼梦 [hong2 lou2 meng4] /Dream of the Red Chamber/\n" \
                 "髮 发 [fa4] /hair (on the head)/\n" \
                 "發 发 [fa1] /to send out/to issue/\n"
        import tempfile
        tmp = os.path.join(tempfile.mkdtemp(), "cedict.txt")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(sample)
        res = build_from_txt(tmp, args.out)
        print("样本验证完成：")
        for k, v in res.items():
            print(f"  {k}: {v['words']} 词 -> {v['ifo']}")
        write_readme(args.out)
        print("已写 README.txt。可用 `python -c` 读取 .idx/.dict 验证。")
        return

    src = args.source
    if not src:
        print("未指定 --source，尝试联网下载 CC-CEDICT …")
        src = fetch_cedict(args.cache)
    if not src or not os.path.isfile(src):
        print("\n⚠ 无法取得 CC-CEDICT 词表（网络受限或未指定 --source）。")
        print("请手动下载 cedict_1_0_ts_utf-8.txt，然后：")
        print("    python kindle/dictbuild.py --source <你的cedict路径>")
        print("推荐下载地址（任选其一）：")
        for u in CEDICT_SOURCES:
            print("    " + u)
        write_readme(args.out)
        sys.exit(2)

    print(f"用词表：{src}")
    res = build_from_txt(src, args.out)
    readme = write_readme(args.out)
    print("\n生成完成：")
    for k, v in res.items():
        print(f"  {k}: {v['words']} 词")
        print(f"      {v['ifo']}")
    print(f"说明见：{readme}")


if __name__ == "__main__":
    main()
