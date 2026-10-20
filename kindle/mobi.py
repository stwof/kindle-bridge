# -*- coding: utf-8 -*-
"""MOBI / AZW / AZW3 / KFX 体检 —— 纯标准库，无第三方依赖。

和 EPUB 的根本区别：这一族是 Kindle **原生**格式，拷进 documents/ 就能直接读，
不需要任何转换。所以本模块不判断"能不能投递"，只回答三个问题：
这份文件是什么格式、有没有加密、能不能在本机直接打开。

四种容易混淆的东西：

  · MOBI / PRC   Mobipocket 时代的老格式（PalmDOC 压缩），兼容最好、排版能力弱
  · AZW          MOBI 家族的老容器，亚马逊下载的书常是这个
  · AZW3 / KF8   2011 年起的新排版引擎，支持 CSS3 与内嵌字体，自建书首选
  · KFX / AZW8   2015 年起的商店格式，只识别不解析（它必定带 DRM）

前三者共用同一套结构：
    Palm Database 外壳（78 字节头 + 记录偏移表）
      └─ 记录 0：PalmDOC 头(16) + MOBI 头 + EXTH 元数据
            └─ 可能再跟一个 "BOUNDARY" 记录，其后是 KF8 版的正文
"""
from __future__ import annotations

import os
import struct

PDB_HEAD = 78
REC_SIZE = 8

ZIP_MAGIC = b"PK\x03\x04"
KFX_MARKS = (b"DRMION", b"CONT")

# PalmDOC 头（记录 0 偏移 0）
PD_COMPRESSION = {0: "不压缩", 1: "不压缩", 2: "PalmDOC", 17480: "HUFF/CDIC"}
PD_ENCRYPTION = {0: "", 1: "Mobipocket 旧版", 2: "Mobipocket"}

# 正文文本编码
TEXT_ENCODING = {0: "cp1252", 1252: "cp1252", 65001: "utf-8", 65002: "utf-16"}

# MOBI 头的 mobi type
MOBI_TYPE = {
    2: "Mobipocket 电子书", 3: "PalmDOC", 4: "音频", 232: "MOBI",
    248: "KF8", 257: "新闻", 258: "新闻订阅", 259: "杂志",
    513: "PICS", 514: "WORD", 515: "XLS", 516: "PPT", 517: "TEXT", 518: "HTML",
}

# EXTH 记录里我们关心的字段（文本类取首个值）
EXTH_TEXT = {
    100: "author", 101: "publisher", 104: "isbn", 105: "subject",
    106: "publishdate", 109: "rights", 112: "source", 113: "asin",
    114: "version", 503: "updated_title", 524: "language",
    204: "creator_software",
}
EXTH_INT = {201: "cover_offset", 202: "thumb_offset", 116: "start_reading"}

# 微信读书「传书到手机」接受的格式
WECHAT_OK = {"epub", "txt", "pdf", "doc", "docx", "mobi", "azw3"}


def _blank(path: str) -> dict:
    """与 epub.py 报告同构，外加 MOBI 专有字段。"""
    return {
        "path": path,
        "name": os.path.basename(path),
        "size": 0,
        "kind": "mobi",
        "valid": False,
        "kindle_ready": False,      # 能投给别的阅读器（微信读书等）
        "kindle_native": False,     # 拷进设备就能读（Kindle 自有格式）
        "drm": False,
        "format": "",
        "format_detail": "",
        "version": "",
        "title": "",
        "author": "",
        "language": "",
        "cover": "",
        "nav": "",
        "fixed_layout": False,
        "spine": 0,
        "images": 0,
        "css": 0,
        "fonts": 0,
        "media": 0,
        "encrypted": False,
        "obfuscated_fonts": False,
        "ascii_name": False,
        "compression": "",
        "encoding": "",
        "records": 0,
        "text_length": 0,
        "kf8": False,
        "kf8_only": False,
        "exth": {},
        "issues": [],
        "warnings": [],
        "notes": [],
    }


def _u32(buf: bytes, off: int) -> int:
    if off < 0 or off + 4 > len(buf):
        raise struct.error(f"偏移 {off} 越界（长度 {len(buf)}）")
    return struct.unpack_from(">I", buf, off)[0]


def sniff(path: str) -> str:
    """只看文件头判断大类：epub / kfx / mobi / unknown。"""
    try:
        with open(path, "rb") as f:
            head = f.read(PDB_HEAD)
    except OSError:
        return "unknown"
    if head[:4] == ZIP_MAGIC:
        return "epub"
    if any(m in head[:64] for m in KFX_MARKS):
        return "kfx"
    if len(head) >= 78 and head[60:64] == b"BOOK":
        return "mobi"
    return "unknown"


def inspect_mobi(path: str) -> dict:
    """把一份 MOBI 家族文件拆开体检，返回结构化报告（不修改任何文件）。"""
    rep = _blank(path)
    err, warn, note = rep["issues"], rep["warnings"], rep["notes"]

    if not os.path.isfile(path):
        err.append({"msg": "文件不存在", "fix": ""})
        return rep
    rep["size"] = os.path.getsize(path)
    rep["ascii_name"] = all(ord(c) < 128 for c in os.path.basename(path))
    ext = os.path.splitext(path)[1].lower()

    try:
        with open(path, "rb") as f:
            head = f.read(PDB_HEAD)
            if len(head) < PDB_HEAD:
                err.append({"msg": "文件不足 78 字节，连 Palm 头都不完整", "fix": "重新获取这份文件"})
                return rep

            # ---- 误传的 EPUB：给准确提示，别让它卡在 Palm 类型报错上 ----
            if head[:4] == ZIP_MAGIC:
                err.append({"msg": "这其实是一份 EPUB（ZIP 容器），不是 MOBI 家族",
                            "fix": "请走 EPUB 通道投递，或用 Send to Kindle 直接发"})
                return rep

            # ---- KFX 单独处理：它不是 Palm 数据库，本模块不解析 ----
            if any(m in head for m in KFX_MARKS):
                rep["format"] = "KFX"
                rep["format_detail"] = "Kindle Ion 容器（2015 年起的商店格式）"
                rep["kindle_native"] = True
                rep["encrypted"] = True
                rep["drm"] = True
                err.append({"msg": "KFX 是加密的商店格式，本工具不做任何解析或解密",
                            "fix": "只能在这台 Kindle 的原生阅读器里读"})
                note.append("KFX 无法转成其他阅读器可读的格式，也不是本工具能处理的对象。")
                return rep

            ptype = head[60:64].decode("latin-1", "replace")
            creator = head[64:68].decode("latin-1", "replace")
            nrec = struct.unpack_from(">H", head, 76)[0]

            if ptype != "BOOK":
                err.append({"msg": f"Palm 类型是 {ptype!r}，不是电子书（应为 'BOOK'）",
                            "fix": "确认这份文件确实是 MOBI/AZW/AZW3"})
                return rep
            if nrec < 2:
                err.append({"msg": f"记录表只有 {nrec} 条，文件可能被截断", "fix": "重新获取这份文件"})
                return rep
            rep["records"] = nrec
            rep["format_detail"] = f"Palm 数据库，creator={creator or '未知'}"

            # ---- 记录偏移表 ----
            f.seek(PDB_HEAD)
            recs: list[int] = []
            for _ in range(nrec):
                ent = f.read(REC_SIZE)
                if len(ent) < REC_SIZE:
                    break
                recs.append(struct.unpack_from(">I", ent, 0)[0])
            if len(recs) < 2:
                err.append({"msg": "记录偏移表损坏", "fix": "重新获取这份文件"})
                return rep
            rep["records"] = len(recs)
            for i in range(len(recs) - 1):
                if recs[i] > recs[i + 1]:
                    warn.append({"msg": f"记录 {i} 的偏移不是递增的，文件可能被改动过",
                                 "fix": "尽量换一份来源"})
                    break

            # ---- 记录 0 ----
            f.seek(recs[0])
            rec0 = f.read(max(recs[1] - recs[0], 16))
            if len(rec0) < 16:
                err.append({"msg": "记录 0 太短，读不到 PalmDOC 头", "fix": "重新获取这份文件"})
                return rep

            comp, text_len, _rec_cnt, _rec_size, enc_type, _unk = struct.unpack_from(
                ">H2xIHHHH", rec0, 0)
            rep["compression"] = PD_COMPRESSION.get(comp, f"未知({comp})")
            rep["text_length"] = text_len
            rep["version"] = ""

            # ---- KF8 边界：双格式 AZW3 的第二个头 ----
            for i in range(1, min(len(recs), 12)):
                f.seek(recs[i])
                if f.read(8) == b"BOUNDARY":
                    rep["kf8"] = True
                    note.append(f"第 {i} 号记录是 KF8 边界，这份文件同时含 MOBI7 与 KF8 两套排版")
                    break

            # ---- MOBI 头 ----
            base = rec0.find(b"MOBI", 16, 16 + 1024)
            if base < 0:
                warn.append({"msg": "记录 0 里没有 MOBI 头（疑似纯 PalmDOC 文件）",
                             "fix": "这类文件只能由 Kindle 原生读取"})
                _finish_format(rep, ext)
                _verdict(rep, ext)
                return rep

            hlen = _u32(rec0, base + 0x04)
            mtype = _u32(rec0, base + 0x08)
            encoding = _u32(rec0, base + 0x0C)
            rep["version"] = str(_u32(rec0, base + 0x14))
            full_off = _u32(rec0, base + 0x44)
            full_len = _u32(rec0, base + 0x48)
            first_img = _u32(rec0, base + 0x5C)
            exth_flags = _u32(rec0, base + 0x70)
            drm_off, drm_cnt, drm_sz, _drm_flags = struct.unpack_from(">4L", rec0, base + 0x98)
            rep["encoding"] = TEXT_ENCODING.get(encoding, f"未知({encoding})")

            codec = TEXT_ENCODING.get(encoding, "utf-8")

            # 完整书名（偏移相对记录 0 起始，不是相对 MOBI 头）
            if 0 < full_off and full_len and full_off + full_len <= len(rec0):
                rep["title"] = rec0[full_off:full_off + full_len].decode(codec, "replace").strip()

            # ---- EXTH ----
            exth = _parse_exth(rec0, base + hlen, codec) if exth_flags & 0x40 else {}
            rep["exth"] = {k: v for k, v in exth.items() if k in EXTH_TEXT}
            if not rep["title"]:
                rep["title"] = (exth.get("updated_title") or "").strip()
            rep["author"] = str(exth.get("author") or "").strip()
            rep["language"] = str(exth.get("language") or "").strip()
            cover_off = exth.get("cover_offset")
            if isinstance(cover_off, int) and first_img:
                rep["cover"] = f"第 {first_img + cover_off} 号记录"

            # ---- 加密：PalmDOC 类型 与 MOBI 的 DRM 段 双重判据 ----
            reasons = []
            if enc_type in PD_ENCRYPTION and enc_type != 0:
                reasons.append(f"PalmDOC 头声明加密（{PD_ENCRYPTION[enc_type]}）")
            if drm_cnt and drm_sz:
                reasons.append(f"MOBI 头里有 DRM 数据段（{drm_cnt} 条 / {drm_sz} 字节）")
            if drm_off and drm_off >= len(rec0) and drm_cnt:
                warn.append({"msg": f"DRM 偏移 {drm_off} 超出记录 0 范围，文件结构异常",
                             "fix": "尽量换一份来源"})
            if reasons:
                rep["drm"] = True
                rep["encrypted"] = True
                err.append({"msg": "含 DRM（" + "；".join(reasons) + "）",
                            "fix": "本工具不做任何解密，这份书只能由 Kindle 原生阅读器打开"})

            _finish_format(rep, ext, mtype, codec)
    except (OSError, struct.error) as ex:
        err.append({"msg": f"解析失败：{type(ex).__name__}: {ex}", "fix": "重新获取这份文件"})
        return rep

    _verdict(rep, ext)
    return rep


def _parse_exth(rec0: bytes, off: int, codec: str) -> dict:
    """读 EXTH 元数据块。字段全丢失也不算错，返回空表即可。"""
    out: dict = {}
    if off + 12 > len(rec0) or rec0[off:off + 4] != b"EXTH":
        return out
    try:
        total, count = struct.unpack_from(">II", rec0, off + 4)
    except struct.error:
        return out
    p = off + 12
    limit = min(off + total, len(rec0))
    for _ in range(count):
        if p + 8 > limit:
            break
        try:
            rtype, rlen = struct.unpack_from(">II", rec0, p)
        except struct.error:
            break
        if rlen < 8 or p + rlen > limit:
            break
        data = rec0[p + 8:p + rlen]
        name = EXTH_TEXT.get(rtype)
        if name and name not in out:
            out[name] = data.decode(codec, "replace").strip()
        elif rtype in EXTH_INT and rtype not in out:
            if len(data) == 4:
                out[EXTH_INT[rtype]] = struct.unpack(">I", data)[0]
        p += rlen
    return out


def _finish_format(rep: dict, ext: str, mtype: int = 0, codec: str = "") -> None:
    """把格式名收敛成人能读的标签。"""
    if rep["kf8"] and ext in (".azw3", ".azw8"):
        rep["format"] = "AZW3"
        rep["format_detail"] = "KF8 排版引擎（MOBI7 + KF8 双格式）"
    elif rep["kf8"]:
        rep["format"] = "AZW3" if ext == ".azw3" else "KF8"
        rep["format_detail"] = "含 KF8 排版引擎"
    elif ext == ".azw3":
        rep["format"] = "AZW3"
        rep["format_detail"] = rep["format_detail"] or "KF8 排版引擎"
    elif ext == ".azw":
        rep["format"] = "AZW"
        rep["format_detail"] = f"MOBI 家族老容器（{MOBI_TYPE.get(mtype, mtype)}）"
    elif ext in (".mobi", ".prc"):
        rep["format"] = "MOBI"
        v = rep["version"]
        rep["format_detail"] = f"MOBI{('' + v) if v else ''}（{MOBI_TYPE.get(mtype, mtype)}）"
    else:
        rep["format"] = "MOBI 家族"
        rep["format_detail"] = rep["format_detail"] or f"{MOBI_TYPE.get(mtype, mtype)}"


def _verdict(rep: dict, ext: str) -> None:
    """结论：这份文件能不能用、怎么用。"""
    err, warn, note = rep["issues"], rep["warnings"], rep["notes"]
    rep["kindle_native"] = True  # MOBI 家族设备原生可读
    rep["valid"] = not err

    if rep["size"] <= 0:
        rep["valid"] = False

    if not rep["title"]:
        warn.append({"msg": "没读到书名元数据，书库里可能显示为文件名", "fix": "无碍阅读；可用 Calibre 补元数据"})
    if rep["encoding"] and rep["encoding"] != "utf-8" and rep["language"].startswith("zh"):
        warn.append({"msg": f"中文书却声明 {rep['encoding']} 编码，个别生僻字可能显示异常",
                     "fix": "用 Calibre 转成 AZW3 可修正"})

    ext_key = ext.lstrip(".")
    if rep["drm"]:
        rep["kindle_ready"] = False
    else:
        rep["kindle_ready"] = ext_key in WECHAT_OK
        if not rep["kindle_ready"]:
            if ext_key == "azw":
                warn.append({"msg": "微信读书不收 .azw 这个老容器",
                             "fix": "用 Calibre 转成 .azw3 或 .mobi 再上传"})
            else:
                warn.append({"msg": f"微信读书不支持 .{ext_key}", "fix": "转成 epub / azw3 / mobi"})

    if not rep["drm"]:
        note.append("Kindle 原生格式，直接拷进设备 documents/ 就能读，不需要转换。")
    note.append(f"设备识别格式：{rep['format'] or '未知'}"
                + (f"（{rep['format_detail']}）" if rep['format_detail'] else ""))


def is_mobi_family(path: str) -> bool:
    """给上传接口用：扩展名 + 文件头双重确认。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mobi", ".azw", ".azw3", ".azw8", ".prc", ".kfx"):
        return True
    return sniff(path) in ("mobi", "kfx")
