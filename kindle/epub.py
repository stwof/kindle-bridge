# -*- coding: utf-8 -*-
"""EPUB 体检 / 修复 / 邮件打包 —— 纯标准库，无第三方依赖。

背景：Kindle 不原生支持 EPUB。
  · 云端路线：Send to Kindle 会把它转成 AZW3/KFX 再送到设备；
  · 离线路线：本地把它转成 AZW3 再拷进 documents/。
两条路能不能走通，前提都是 EPUB 本身结构合法 —— 最常见的失败
（Amazon 的通用报错 E999）多半来自压缩包结构而非正文内容。
所以本模块在投递前先把文件体检一遍，并修掉那几处硬伤。
"""
from __future__ import annotations

import datetime
import os
import re
import zipfile
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from xml.etree import ElementTree as ET

from . import hanzi

CONTAINER = "META-INF/container.xml"
ENCRYPTION = "META-INF/encryption.xml"
SIGNATURES = "META-INF/signatures.xml"

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "enc": "http://www.w3.org/2001/04/xmlenc#",
    "sig": "http://www.w3.org/2000/09/xmldsig#",
}

FONT_EXT = (".ttf", ".otf", ".ttc", ".woff", ".woff2")
MEDIA_EXT = (".mp3", ".mp4", ".m4a", ".ogg", ".webm", ".mpg")
ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _blank(path: str) -> dict:
    return {
        "path": path,
        "name": os.path.basename(path),
        "size": 0,
        "kind": "epub",
        "valid": False,
        "kindle_ready": False,
        "kindle_native": False,      # EPUB 不在 Kindle 固件的渲染器里
        "drm": False,
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
        "issues": [],
        "warnings": [],
        "notes": [],
    }


def _xml(data: bytes):
    try:
        return ET.fromstring(data)
    except (ET.ParseError, ValueError):
        return None


def _first(node, tag: str) -> str:
    if node is None:
        return ""
    el = node.find(tag, NS)
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _resolve(base_dir: str, href: str) -> str:
    href = href.split("#", 1)[0].split("?", 1)[0]
    href = href.replace("\\", "/")
    parts: list[str] = []
    for seg in (base_dir.split("/") if base_dir else []) + href.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def inspect_epub(path: str) -> dict:
    """把一份 EPUB 拆开体检，返回结构化报告（不修改任何文件）。"""
    rep = _blank(path)
    err, warn, note = rep["issues"], rep["warnings"], rep["notes"]

    if not os.path.isfile(path):
        err.append({"msg": "文件不存在", "fix": ""})
        return rep
    rep["size"] = os.path.getsize(path)
    rep["ascii_name"] = all(ord(c) < 128 for c in os.path.basename(path))

    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as ex:
        err.append({"msg": f"不是有效的 zip/epub（{ex}）", "fix": "重新下载或换一份来源"})
        return rep

    with zf:
        names = zf.namelist()
        name_set = set(names)

        # ---- 1. mimetype ----
        if "mimetype" not in name_set:
            err.append({"msg": "缺少 mimetype 文件", "fix": "点「修复并打包」自动补上"})
        else:
            info = zf.getinfo("mimetype")
            if names[0] != "mimetype":
                warn.append({"msg": "mimetype 不是压缩包里的第一个条目（规范硬要求，Send to Kindle 常因此拒收）",
                             "fix": "点「修复并打包」"})
            if info.compress_type != zipfile.ZIP_STORED:
                warn.append({"msg": "mimetype 被压缩了（规范要求不压缩）", "fix": "点「修复并打包」"})
            try:
                if zf.read("mimetype").strip() != b"application/epub+zip":
                    warn.append({"msg": "mimetype 内容不是 application/epub+zip", "fix": "点「修复并打包」"})
            except (KeyError, OSError):
                pass

        junk = [n for n in names if n.startswith("__MACOSX/") or n.endswith(".DS_Store")]
        if junk:
            warn.append({"msg": f"含 {len(junk)} 个 macOS 冗余文件（__MACOSX / .DS_Store）",
                         "fix": "点「修复并打包」清除"})

        # ---- 2. container.xml → OPF ----
        opf_path = ""
        if CONTAINER not in name_set:
            err.append({"msg": "缺少 META-INF/container.xml，这不是一个合法 EPUB", "fix": "无法自动修复，请换一份文件"})
        else:
            root = _xml(zf.read(CONTAINER))
            if root is None:
                err.append({"msg": "container.xml 解析失败", "fix": "换一份文件"})
            else:
                rf = root.find("c:rootfiles/c:rootfile", NS)
                if rf is not None:
                    opf_path = (rf.get("full-path") or "").replace("\\", "/")
                if not opf_path:
                    err.append({"msg": "container.xml 里没有指向 OPF 的 rootfile", "fix": "换一份文件"})
                elif opf_path not in name_set:
                    err.append({"msg": f"container.xml 指向的 OPF（{opf_path}）在压缩包里不存在", "fix": "换一份文件"})

        # ---- 3. OPF ----
        base_dir = os.path.dirname(opf_path).replace("\\", "/") if opf_path else ""
        if opf_path and opf_path in name_set:
            root = _xml(zf.read(opf_path))
            if root is None:
                err.append({"msg": "OPF 内容 XML 语法错误，无法解析", "fix": "用 Calibre 重新导出"})
            else:
                rep["version"] = root.get("version", "") or ""
                md = root.find("opf:metadata", NS)
                rep["title"] = _first(md, "dc:title")
                rep["author"] = _first(md, "dc:creator")
                rep["language"] = _first(md, "dc:language")

                # 固定版式
                if md is not None:
                    for m in md.findall("opf:meta", NS):
                        prop = (m.get("property") or "").strip()
                        nm = (m.get("name") or "").strip().lower()
                        val = (m.get("content") or m.text or "").strip()
                        if prop == "rendition:layout" and val == "pre-paginated":
                            rep["fixed_layout"] = True
                        if nm in ("fixed-layout", "original-resolution") and val.lower() in ("true", "yes"):
                            rep["fixed_layout"] = True

                # manifest
                manifest = root.find("opf:manifest", NS)
                ids: dict[str, dict] = {}
                cover_id = ""
                if md is not None:
                    for m in md.findall("opf:meta", NS):
                        if (m.get("name") or "").lower() == "cover":
                            cover_id = (m.get("content") or "").strip()
                if manifest is not None:
                    for it in manifest.findall("opf:item", NS):
                        href = (it.get("href") or "").replace("\\", "/")
                        props = (it.get("properties") or "")
                        mtype = (it.get("media-type") or "").lower()
                        iid = it.get("id") or ""
                        ids[iid] = {"href": href, "props": props, "type": mtype}
                        low = href.lower()
                        if low.endswith(".jpg") or low.endswith(".jpeg") or low.endswith(".png") \
                                or low.endswith(".gif") or low.endswith(".webp"):
                            rep["images"] += 1
                        elif low.endswith(".css"):
                            rep["css"] += 1
                        elif low.endswith(FONT_EXT):
                            rep["fonts"] += 1
                        elif low.endswith(MEDIA_EXT) or mtype.startswith(("audio/", "video/")):
                            rep["media"] += 1
                        if "cover-image" in props:
                            rep["cover"] = href
                        if "nav" in props.split():
                            rep["nav"] = href
                        if "scripted" in props.split():
                            warn.append({"msg": f"含脚本内容（{href}），Kindle 阅读器不执行脚本，功能会缺失", "fix": ""})
                    if cover_id and cover_id in ids:
                        rep["cover"] = rep["cover"] or ids[cover_id]["href"]
                    if not rep["nav"]:
                        for iid, it in ids.items():
                            if it["type"] == "application/x-dtbncx+xml":
                                rep["nav"] = it["href"]
                                break

                # spine
                spine = root.find("opf:spine", NS)
                refs = spine.findall("opf:itemref", NS) if spine is not None else []
                rep["spine"] = len(refs)

                # 资源完整性：manifest 里点名的文件是否真在包里
                missing = []
                for iid, it in ids.items():
                    if not it["href"]:
                        continue
                    if _resolve(base_dir, it["href"]) not in name_set:
                        missing.append(it["href"])
                if missing:
                    err.append({"msg": f"{len(missing)} 个资源在包里找不到（如 {', '.join(missing[:3])}）",
                                "fix": "文件被裁剪过，建议换一份完整来源"})

                if not rep["title"]:
                    warn.append({"msg": "缺少书名（dc:title），导入后会显示为文件名", "fix": "可在 Calibre 里补"})
                if not rep["language"]:
                    warn.append({"msg": "缺少语言标记（dc:language）", "fix": "可在 Calibre 里补"})
                if rep["spine"] == 0:
                    err.append({"msg": "spine 为空，没有正文可读", "fix": "换一份文件"})

        # ---- 4. 加密 / DRM ----
        if ENCRYPTION in name_set:
            rep["encrypted"] = True
            enc = _xml(zf.read(ENCRYPTION))
            if enc is None:
                warn.append({"msg": "存在 encryption.xml 但解析失败", "fix": ""})
            else:
                refs = [r.get("URI", "") for r in enc.iter() if r.tag.endswith("CipherReference")]
                if not refs:
                    refs = [r.text or "" for r in enc.iter() if r.tag.endswith("CipherReference")]
                content_refs = [r for r in refs if not r.lower().endswith(FONT_EXT)]
                font_refs = [r for r in refs if r.lower().endswith(FONT_EXT)]
                if content_refs:
                    rep["drm"] = True
                    err.append({"msg": "正文被加密（Adobe ADEPT 等 DRM），Send to Kindle 与 Calibre 都无法处理",
                                "fix": "本工具不做任何破解，请使用正版渠道或换无 DRM 的来源"})
                if font_refs:
                    rep["obfuscated_fonts"] = True
                    note.append(f"内嵌字体做了混淆保护（{len(font_refs)} 个），属正常现象，可正常发送")
        if SIGNATURES in name_set:
            note.append("含 META-INF/signatures.xml（部分商店 EPUB 的数字签名），一般不影响阅读")

        if rep["fixed_layout"]:
            warn.append({"msg": "这是固定版式 EPUB（漫画/画册常见），转 AZW3 后字号不可调，6 吋屏体验一般",
                         "fix": "可考虑转成 PDF 阅读"})
        if rep["media"]:
            warn.append({"msg": f"含 {rep['media']} 个音视频资源，Kindle 个人文档不支持播放", "fix": ""})
        if not rep["cover"]:
            note.append("没有检测到封面图，书库里会显示为默认封面")
        if not rep["ascii_name"]:
            note.append("文件名含非 ASCII 字符：通常没问题，若 Send to Kindle 报错可先重命名再发")

    rep["valid"] = not rep["issues"]
    rep["kindle_ready"] = rep["valid"] and not rep["drm"]
    return rep


def repair_epub(src: str, dst: str) -> dict:
    """按 EPUB 规范重排压缩包：mimetype 置顶且不压缩，清除 macOS 冗余文件。

    只动容器结构，不改正文内容 —— 这是最保守、也最有效的修复。
    """
    changed: list[str] = []
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ValueError("源文件与目标文件不能相同")

    with zipfile.ZipFile(src) as zin:
        entries = []
        for info in zin.infolist():
            if info.filename.startswith("__MACOSX/") or info.filename.endswith(".DS_Store"):
                changed.append("移除 " + info.filename)
                continue
            blob = b"" if info.is_dir() else zin.read(info.filename)
            entries.append((info, blob))

    has_mimetype = any(i.filename == "mimetype" for i, _ in entries)
    if not has_mimetype:
        changed.append("补上 mimetype")

    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr(_stored_zipinfo("mimetype"), b"application/epub+zip")
        for info, blob in entries:
            if info.filename == "mimetype":
                if blob.strip() != b"application/epub+zip":
                    changed.append("修正 mimetype 内容")
                continue
            zout.writestr(info, blob)

    if not changed:
        changed.append("结构已合规，仅重新打包")
    return {"ok": True, "out": dst, "changed": changed}


# 转换时要原样保护的东西：style / script 整块，以及任何标签本身。
# 少了这层保护，「<title>紅樓夢</title>」里的标签会被当成文本一起改掉，EPUB 直接坏。
_SKIP_BLOCK = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
_ANY_TAG = re.compile(r"<[^>]*>")
# 需要转换正文的扩展名。图片、字体、音视频一律不动。
_TEXTUAL = (".xhtml", ".html", ".htm", ".opf", ".ncx")


def _convert_between_tags(seg: str, conv) -> str:
    """改标签之间的文本，标签本身一字不动。

    `<[^>]*>` 顺带把 XML 声明、注释、CDATA 也当成标签保护起来 ——
    这些地方本来就不该动，一并省了心。
    conv 是具体的转换器（hanzi.to_simplified / hanzi.to_traditional / hanzi.convert）。
    """
    if not seg:
        return seg
    res: list[str] = []
    pos = 0
    for m in _ANY_TAG.finditer(seg):
        res.append(conv(seg[pos:m.start()]))
        res.append(m.group(0))
        pos = m.end()
    res.append(conv(seg[pos:]))
    return "".join(res)


def _convert_markup(doc: str, conv) -> str:
    out: list[str] = []
    pos = 0
    for m in _SKIP_BLOCK.finditer(doc):
        out.append(_convert_between_tags(doc[pos:m.start()], conv))
        out.append(m.group(0))
        pos = m.end()
    out.append(_convert_between_tags(doc[pos:], conv))
    return "".join(out)


def _pick_converter(to: str):
    """根据目标字体选转换器。默认 auto（自动判别当前字体再转成另一边）。"""
    to = (to or "auto").strip().lower()
    if to in ("traditional", "繁体", "trad"):
        return hanzi.to_traditional
    if to in ("simplified", "简体", "simp"):
        return hanzi.to_simplified
    return hanzi.convert          # auto


def convert_epub(src: str, dst: str, to: str = "simplified") -> dict:
    """把 EPUB 的正文与元数据转成目标字体（simplified/traditional/auto），
    容器结构保持合法。

    古登堡的中文书几乎全是繁体，可一步变成能舒服读的简体；反过来也有人
    想把手上的简体书转成繁体放到 KOReader 上读。
    只动文本节点：标签、style、script、图片字体一律原样，
    产出仍然是 mimetype 置顶且不压缩的合法 EPUB。
    """
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ValueError("源文件与目标文件不能相同")
    conv = _pick_converter(to)

    entries: list[list] = []
    with zipfile.ZipFile(src) as zin:
        for info in zin.infolist():
            entries.append([info, b"" if info.is_dir() else zin.read(info.filename)])

    try:
        old_title = inspect_epub(src).get("title") or ""
    except Exception:
        old_title = ""

    converted: list[str] = []
    for item in entries:
        info, blob = item
        if not blob or info.is_dir():
            continue
        if os.path.splitext(info.filename)[1].lower() not in _TEXTUAL:
            continue
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            continue                    # 非 UTF-8 的文件改了容易出事，宁可不碰
        if not hanzi.looks_chinese(text):
            continue
        new = _convert_markup(text, conv)
        if new != text:
            item[1] = new.encode("utf-8")
            converted.append(info.filename)

    new_title = conv(old_title) if old_title else ""
    direction = "繁体" if (to in ("traditional", "繁体", "trad")) else (
        "简体" if to in ("simplified", "简体", "simp") else "自动")

    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr(_stored_zipinfo("mimetype"), b"application/epub+zip")
        for info, blob in entries:
            if info.filename == "mimetype":
                continue
            zout.writestr(info, blob)

    changed = [f"正文转{direction}：{len(converted)} 个文件"] if converted else [f"正文已是{direction}，未改动"]
    if old_title and new_title and new_title != old_title:
        changed.append(f"书名：{old_title} → {new_title}")

    return {"ok": True, "out": dst, "direction": direction,
            "title_before": old_title,
            "title_after": new_title or old_title,
            "converted": converted, "changed": changed}


def to_simplified_epub(src: str, dst: str) -> dict:
    """把 EPUB 的正文与元数据转成简体（兼容旧调用）。"""
    return convert_epub(src, dst, to="simplified")


def to_traditional_epub(src: str, dst: str) -> dict:
    """把 EPUB 的正文与元数据转成繁体。"""
    return convert_epub(src, dst, to="traditional")


def _esc(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace('"', "&quot;")


def _xhtml(title: str, paras: list[str]) -> str:
    body = "".join(f"    <p>{_esc(p)}</p>\n" for p in paras if p and p.strip())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
        '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh">\n'
        "<head>\n"
        f"  <title>{_esc(title)}</title>\n"
        '  <link rel="stylesheet" type="text/css" href="style.css"/>\n'
        "</head>\n"
        "<body>\n"
        f"  <h2>{_esc(title)}</h2>\n"
        f"{body}"
        "</body>\n</html>\n"
    )


def build_epub(title: str, author: str, chapters: list[tuple[str, list[str]]],
               out: str, language: str = "zh",
               description: str = "") -> dict:
    """把「章节标题 + 段落」直接打包成一份合法的 EPUB 2.0。

    中文古籍数据源（如 chinese-poetry）给的是纯文本 JSON，要送到 Kindle 上
    必须先变成容器合法的书。这里只产 EPUB 2.0 —— Kindle 走 Calibre 转 AZW3
    时，2.0（带 NCX 目录）比 3.0 稳，不会出现空目录。

    chapters 为空时返回 ok=False，绝不产出没有内容的空壳书。
    """
    chapters = [(t, [p for p in ps if p and p.strip()]) for t, ps in chapters]
    chapters = [(t, ps) for t, ps in chapters if ps]
    if not chapters:
        return {"ok": False, "error": "没有可打包的正文"}

    safe_title = _esc(title or "未命名")
    safe_author = _esc(author or "")
    n = len(chapters)

    def pad(i: int) -> str:
        return f"{i:04d}"

    manifest = []
    spine = []
    navpoints = []
    for i, (ctitle, paras) in enumerate(chapters, 1):
        fid = f"chap{pad(i)}"
        href = f"{fid}.xhtml"
        manifest.append(f'    <item id="{fid}" href="{href}" media-type="application/xhtml+xml"/>')
        spine.append(f'    <itemref idref="{fid}"/>')
        navpoints.append(
            f'    <navPoint id="nav{i}" playOrder="{i}">\n'
            f'      <navLabel><text>{_esc(ctitle or f"第{i}篇")}</text></navLabel>\n'
            f'      <content src="{href}"/>\n'
            "    </navPoint>"
        )

    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">\n'
        f"    <dc:title>{safe_title}</dc:title>\n"
        f"    <dc:creator opf:role=\"aut\">{safe_author}</dc:creator>\n"
        f"    <dc:language>{language}</dc:language>\n"
        '    <dc:identifier id="bookid">urn:uuid:' + _uuid() + "</dc:identifier>\n"
        + (f"    <dc:description>{_esc(description)}</dc:description>\n" if description else "")
        + "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
        '    <item id="css" href="style.css" media-type="text/css"/>\n'
        + "\n".join(manifest) + "\n"
        "  </manifest>\n"
        f'  <spine toc="ncx">\n' + "\n".join(spine) + "\n  </spine>\n"
        "</package>\n"
    )

    ncx = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        "  <head>\n"
        f'    <meta name="dtb:uid" content="urn:uuid:{_uuid()}"/>\n'
        "  </head>\n"
        "  <docTitle><text>" + safe_title + "</text></docTitle>\n"
        "  <navMap>\n" + "\n".join(navpoints) + "\n  </navMap>\n"
        "</ncx>\n"
    )

    css = (
        "body { margin: 1.2em; line-height: 1.75; }\n"
        "h2 { font-size: 1.15em; margin: 1.4em 0 0.8em; text-align: center; }\n"
        "p { margin: 0 0 0.7em; text-indent: 0; }\n"
    )

    container = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">\n'
        '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles>\n'
        "</container>\n"
    )

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    tmp = out + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(_stored_zipinfo("mimetype"), b"application/epub+zip")
        z.writestr("META-INF/container.xml", container.encode("utf-8"))
        z.writestr("OEBPS/content.opf", opf.encode("utf-8"))
        z.writestr("OEBPS/toc.ncx", ncx.encode("utf-8"))
        z.writestr("OEBPS/style.css", css.encode("utf-8"))
        for i, (ctitle, paras) in enumerate(chapters, 1):
            z.writestr(f"OEBPS/chap{pad(i)}.xhtml",
                       _xhtml(ctitle or f"第{i}篇", paras).encode("utf-8"))
    os.replace(tmp, out)

    return {"ok": True, "out": out, "title": title, "author": author,
            "chapters": n, "paras": sum(len(p) for _, p in chapters),
            "size": os.path.getsize(out)}


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


def _stored_zipinfo(name: str) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    zi.compress_type = zipfile.ZIP_STORED
    zi.external_attr = 0o644 << 16
    return zi


def safe_filename(name: str, max_len: int = 80) -> str:
    name = ILLEGAL.sub("_", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "untitled"


def make_eml(epub_path: str, to_addr: str, from_addr: str = "",
             subject: str = "", body: str = "") -> bytes:
    """生成一封「附件已就绪」的 .eml —— 双击用邮件客户端打开，点发送即可。"""
    title = os.path.splitext(os.path.basename(epub_path))[0]
    msg = MIMEMultipart()
    msg["To"] = to_addr or "your-kindle-address@kindle.com"
    if from_addr:
        msg["From"] = from_addr
    msg["Subject"] = Header(subject or f"传书：{title}", "utf-8")
    msg["Date"] = datetime.datetime.now().strftime("%a, %d %b %Y %H:%M:%S %z") or ""

    intro = body or (
        "这封邮件由「Kindle 桥」生成，附件是一本已体检通过的 EPUB。\n"
        "发送前请确认：\n"
        "  1. 收件人是你 Kindle 的 @kindle.com 专属地址；\n"
        "  2. 你的发件邮箱已加入亚马逊「已批准的个人文档电子邮件列表」；\n"
        "  3. Kindle 已连上 Wi-Fi。\n"
        "发送后约 1~2 分钟，书本会出现在设备的「个人文档」里。\n"
    )
    msg.attach(MIMEText(intro, "plain", "utf-8"))

    with open(epub_path, "rb") as f:
        part = MIMEApplication(f.read(), _subtype="epub+zip")
    part.add_header("Content-Disposition", "attachment",
                    filename=("utf-8", "", os.path.basename(epub_path)))
    msg.attach(part)
    return msg.as_bytes()
