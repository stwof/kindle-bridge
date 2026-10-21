# -*- coding: utf-8 -*-
"""MOBI 体检的自测：自造样本 + 用设备上的真实文件交叉验证。

自造样本覆盖各种"病症"，真实文件（azw3 / azw / kfx）用来确认
判定在亚马逊真实产物上同样成立 —— 尤其是 DRM 与 KFX 的识别。
"""
from __future__ import annotations

import os
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kindle import mobi as M  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mobi-samples")
DEVICE = r"E:\documents"


# ----------------------------------------------------------------- 造样本
def build_mobi(title: str, author: str, *, version: int = 6, mtype: int = 2,
               encoding: int = 65001, drm: bool = False, encrypt_flag: int = 0,
               kf8: bool = False, pdb_type: bytes = b"BOOK", nrec_hint: int | None = None,
               truncate: int = 0, name_field: str = "TESTBOOK"):
    """拼一个结构合法的 MOBI 家族文件（字段位置严格按 MOBI 规范）。"""
    codec = "utf-8" if encoding == 65001 else "cp1252"
    body = ("The quick brown fox jumps over the lazy dog. " * 30).encode(codec)

    # EXTH：作者 / 书名 / 语言
    chunks = []

    def add(t: int, data: bytes) -> None:
        chunks.append(struct.pack(">II", t, len(data) + 8) + data)

    add(100, author.encode(codec))
    add(503, title.encode(codec))
    add(524, b"en")
    exth_body = b"".join(chunks)
    exth = b"EXTH" + struct.pack(">II", len(exth_body) + 12, len(chunks)) + exth_body

    # MOBI 头（232 字节）
    HLEN = 232
    mobi = bytearray(HLEN)
    mobi[0:4] = b"MOBI"
    struct.pack_into(">I", mobi, 0x04, HLEN)
    struct.pack_into(">I", mobi, 0x08, mtype)
    struct.pack_into(">I", mobi, 0x0C, encoding)
    struct.pack_into(">I", mobi, 0x10, 0xBEEF)
    struct.pack_into(">I", mobi, 0x14, version)
    struct.pack_into(">I", mobi, 0x5C, 1)          # first image index
    struct.pack_into(">I", mobi, 0x70, 0x40)       # EXTH flags 置位

    name_b = title.encode(codec)
    full_off = 16 + HLEN + len(exth)
    struct.pack_into(">I", mobi, 0x44, full_off)   # full name offset（相对记录 0）
    struct.pack_into(">I", mobi, 0x48, len(name_b))

    drm_block = b""
    if drm:
        drm_block = b"\x00\x00\x00\x43\x00\x00\x00\x30" + b"\xAB" * 40
        struct.pack_into(">4L", mobi, 0x98, full_off + len(name_b), 1, len(drm_block), 1)

    palm = struct.pack(">H2xIHHHH", 2, len(body), 1, 4096, encrypt_flag or (2 if drm else 0), 0)
    rec0 = palm + bytes(mobi) + exth + name_b + drm_block

    # 记录表：KF8 时插入 BOUNDARY 与第二套头
    if kf8:
        kf8_head = bytearray(rec0)
        struct.pack_into(">I", kf8_head, 16 + 0x08, 248)   # mobi type = KF8
        struct.pack_into(">I", kf8_head, 16 + 0x14, 8)     # version = 8
        records = [rec0, b"BOUNDARY", bytes(kf8_head), body]
    else:
        records = [rec0, body]
    if nrec_hint is not None:
        records = records[:nrec_hint]

    # PDB 外壳
    offs = []
    pos = 78 + 8 * len(records)
    for r in records:
        offs.append(pos)
        pos += len(r)

    head = bytearray(78)
    head[0:len(name_field)] = name_field.encode("latin-1")
    struct.pack_into(">H", head, 32, 0)
    struct.pack_into(">H", head, 34, 0)
    head[60:64] = pdb_type
    head[64:68] = b"MOBI"
    struct.pack_into(">I", head, 68, 1)
    struct.pack_into(">H", head, 76, len(records))

    blob = bytes(head)
    for i, r in enumerate(records):
        blob += struct.pack(">IBBH", offs[i], 0, 0, i)
    for r in records:
        blob += r
    if truncate:
        blob = blob[:truncate]
    return blob


def write(name: str, blob: bytes) -> str:
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with open(p, "wb") as f:
        f.write(blob)
    return p


def make_samples() -> list[str]:
    made = []
    made.append(write("01-正常MOBI6.mobi",
                      build_mobi("测试书 · 正常样本", "某作者")))
    made.append(write("02-双格式AZW3.azw3",
                      build_mobi("测试书 · 双格式", "某作者", kf8=True, version=8)))
    made.append(write("03-带DRM的AZW.azw",
                      build_mobi("测试书 · 加密", "某作者", drm=True, name_field="CR!ZY71PGADTN4CH")))
    made.append(write("04-纯KF8.kfx", b"\xeaDRMION\xee\xe0\x01\x00\xea\xee\x9e\x81\x83" + b"\x00" * 200))
    made.append(write("05-截断文件.mobi", build_mobi("坏文件", "x", truncate=40)))
    made.append(write("06-其实是EPUB.mobi", b"PK\x03\x04" + b"\x00" * 300))
    made.append(write("07-非电子书.mobi",
                      build_mobi("x", "y", pdb_type=b"DATA", nrec_hint=2)))

    ep = os.path.join(OUT, "08-真EPUB.epub")
    with zipfile.ZipFile(ep, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", "<container/>")
    made.append(ep)
    return made


# ----------------------------------------------------------------- 跑测试
def main() -> int:
    fails: list[str] = []
    made = make_samples()

    print("=" * 78)
    print("A. 自造样本")
    print("=" * 78)
    for p in made:
        r = M.inspect_mobi(p)
        print(f"\n{os.path.basename(p)}")
        print(f"  sniff={M.sniff(p):<8} format={r['format']:<10} valid={r['valid']:<5} "
              f"drm={r['drm']:<5} native={r['kindle_native']:<5} ready={r['kindle_ready']}")
        print(f"  书名={r['title']!r} 作者={r['author']!r} 语言={r['language']!r} "
              f"记录={r['records']} 压缩={r['compression']} 编码={r['encoding']} kf8={r['kf8']}")
        for i in r["issues"]:
            print("   [必须]", i["msg"])
        for w in r["warnings"]:
            print("   [注意]", w["msg"])
        for n in r["notes"]:
            print("   [说明]", n)

    # 断言
    def check(cond, msg):
        if not cond:
            fails.append(msg)

    r = M.inspect_mobi(made[0])
    check(r["format"] == "MOBI" and not r["drm"] and r["valid"], "01 应为无 DRM 的正常 MOBI")
    check(r["title"] == "测试书 · 正常样本" and r["author"] == "某作者", "01 元数据应正确")
    check(r["kindle_native"] and r["kindle_ready"], "01 应可原生读且可投给微信读书")
    check(r["compression"] == "PalmDOC" and r["encoding"] == "utf-8", "01 压缩/编码应正确")

    r = M.inspect_mobi(made[1])
    check(r["kf8"] and r["format"] == "AZW3", "02 应识别为双格式 AZW3")

    r = M.inspect_mobi(made[2])
    check(r["drm"] and not r["kindle_ready"], "03 应判出 DRM 且不可外投")
    check(r["format"] == "AZW", "03 格式应为 AZW")

    r = M.inspect_mobi(made[3])
    check(r["format"] == "KFX" and r["drm"], "04 应为 KFX 且带 DRM")

    r = M.inspect_mobi(made[4])
    check(not r["valid"], "05 截断文件应判为不合格")

    r = M.inspect_mobi(made[5])
    check(M.sniff(made[5]) == "epub", "06 sniff 应识别为 epub")
    check("EPUB" in r["issues"][0]["msg"], "06 应给出「其实是 EPUB」的准确提示")

    check(M.sniff(made[0]) == "mobi", "01 sniff 应识别为 mobi")
    check(M.sniff(made[1]) == "mobi", "02 sniff 应识别为 mobi")
    check(M.sniff(made[3]) == "kfx", "04 sniff 应识别为 kfx")
    check(M.sniff(made[4]) == "unknown", "05 截断文件 sniff 应为 unknown")

    r = M.inspect_mobi(made[6])
    check(not r["valid"], "07 非电子书应判为不合格")

    print("\n" + "=" * 78)
    print("B. 设备上的真实亚马逊文件")
    print("=" * 78)
    real = []
    # 没连 Kindle 时 E:\documents 根本不存在，这一段只能跳过 —— 不然整个测试
    # 会以 FileNotFoundError 崩掉，让人误以为代码坏了。
    if not os.path.isdir(DEVICE):
        print(f"  [SKIP] 没检测到 Kindle 设备目录 {DEVICE}，跳过「设备上的真实文件」")
        real = []
    else:
        for n in sorted(os.listdir(DEVICE)):
            if n.lower().endswith((".kfx", ".azw3", ".azw")):
                real.append(os.path.join(DEVICE, n))
    for p in real:
        r = M.inspect_mobi(p)
        print(f"  {os.path.basename(p)[:46]:<48} {r['format']:<6} drm={str(r['drm']):<5} "
              f"ready={str(r['kindle_ready']):<5} 记录={r['records']:<6} "
              f"压缩={r['compression']:<9} 编码={r['encoding']}")
    kfx = [p for p in real if p.lower().endswith(".kfx")]
    azw = [p for p in real if p.lower().endswith((".azw", ".azw3"))]
    if not real:
        print("  [SKIP] 设备目录里没有 kfx/azw 文件，这三条依赖真实文件的断言一并跳过")
    else:
        check(len(kfx) >= 1 and all(M.inspect_mobi(p)["format"] == "KFX" for p in kfx),
              "所有真实 kfx 都应判为 KFX")
        check(all(M.inspect_mobi(p)["drm"] for p in real), "真实亚马逊文件应全部判出 DRM")
        check(all(not M.inspect_mobi(p)["kindle_ready"] for p in real),
              "带 DRM 的真实文件都不应可外投")

    print("\n" + "=" * 78)
    if fails:
        print("失败项：")
        for f in fails:
            print("  ✗", f)
        return 1
    print("全部断言通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
