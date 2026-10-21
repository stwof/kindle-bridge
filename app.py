# -*- coding: utf-8 -*-
"""Kindle 桥 —— 把 Kindle 的标注、生词与书籍，桥接到微信读书等国内阅读工具。

用法：
    python app.py                    # 启动本地服务并自动打开浏览器
    python app.py --port 8765        # 指定端口
    python app.py --no-browser       # 不自动开浏览器
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import posixpath
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from kindle import paths as paths_mod                 # noqa: E402

# 只读资源（web/）与用户数据（导出/ 收书/）分家：打成 exe 后资源在解包目录里，
# 数据必须落在 exe 旁边，否则用户放的书会跟着临时目录一起消失。
RES_DIR = paths_mod.resource_dir()
WEB_DIR = os.path.join(RES_DIR, "web")
BASE_DIR = paths_mod.data_dir()
OUT_DIR = os.path.join(BASE_DIR, "导出")
INBOX_DIR = os.path.join(BASE_DIR, "收书")        # 待投递的电子书放这里

from kindle import calibre as cal_mod            # noqa: E402
from kindle import classics as cls_mod           # noqa: E402
from kindle import clippings as clip_mod          # noqa: E402
from kindle import convert as conv_mod            # noqa: E402
from kindle import deliver as deliv_mod           # noqa: E402
from kindle import device as dev_mod              # noqa: E402
from kindle import epub as epub_mod               # noqa: E402
from kindle import exporter as exp_mod            # noqa: E402
from kindle import freebooks as free_mod          # noqa: E402
from kindle import library as lib_mod             # noqa: E402
from kindle import vocab as vocab_mod             # noqa: E402
from kindle import zhconv_file as zcf_mod          # noqa: E402
from kindle import hanzi as hanzi_mod               # noqa: E402
from kindle import tts as tts_mod                   # noqa: E402
from kindle import reader as reader_mod             # noqa: E402
from kindle import dictdata as dictdata_mod         # noqa: E402

# 「收书」接受的输入：EPUB 需要转换投递；MOBI 家族设备原生可读，零转换直投
INBOX_EXTS = (".epub", ".mobi", ".azw", ".azw3", ".prc")

_CACHE: dict = {"at": 0.0, "data": None, "device": None}
_LOCK = threading.Lock()
CACHE_TTL = 20


def collect(force: bool = False) -> dict:
    """汇总设备、书库、标注、生词数据（带短缓存）。"""
    with _LOCK:
        if not force and _CACHE["data"] and time.time() - _CACHE["at"] < CACHE_TTL:
            return _CACHE["data"]

        device = dev_mod.find_kindle()
        result: dict = {
            "device": device.to_dict() if device else None,
            "calibre": conv_mod.find_ebook_convert() or "",
            "library": {"books": [], "orphans": []},
            "highlights": {"groups": [], "stats": {"total": 0, "books": 0, "types": {}}},
            "vocab": {"words": [], "stats": {"total": 0, "zh": 0, "en": 0, "lookups": 0}},
        }
        if device:
            result["library"] = lib_mod.scan_library(device)

            vocab_raw = (vocab_mod.read_vocab(device.vocab_db)
                         if os.path.isfile(device.vocab_db)
                         else {"words": [], "books": [], "stats": {"total": 0, "zh": 0, "en": 0, "lookups": 0}})
            _enrich_library_authors(result["library"]["books"], vocab_raw["books"])

            if os.path.isfile(device.clippings):
                clips = clip_mod.parse_clippings(device.clippings)
                groups = clip_mod.group_by_book(clips)
                groups = _enrich_authors(groups, device, vocab_raw["books"])
                types: dict[str, int] = {}
                for c in clips:
                    types[c.type] = types.get(c.type, 0) + 1
                result["highlights"] = {
                    "groups": groups,
                    "stats": {"total": len(clips), "books": len(groups), "types": types},
                }

            result["vocab"] = {"words": vocab_raw["words"], "stats": vocab_raw["stats"]}

        _CACHE.update({"at": time.time(), "data": result, "device": device})
        return result


def _enrich_library_authors(books: list[dict], vocab_books: list[dict]) -> None:
    """用生词本的书籍元数据补全书库作者。"""
    for b in books:
        if b.get("author"):
            continue
        t = (b.get("title") or "").strip()
        for vb in vocab_books:
            vt = (vb.get("title") or "").strip()
            if vt and (vt.startswith(t[:10]) or t.startswith(vt[:10])) and vb.get("authors"):
                b["author"] = vb["authors"]
                break


def _enrich_authors(groups: list[dict], device, vocab_books: list[dict]) -> list[dict]:
    """用 metadata.calibre / 生词本补全作者。"""
    meta = lib_mod.load_calibre_metadata(device.root)
    lookup = {}
    for stem, info in meta.items():
        t = info.get("title", "")
        if t:
            lookup[t] = info.get("author", "")

    for b in vocab_books or []:
        t = (b.get("title") or "").strip()
        if t and b.get("authors"):
            lookup.setdefault(t, b["authors"])

    for g in groups:
        if g.get("author"):
            continue
        title = g["title"].strip()
        if title in lookup and lookup[title]:
            g["author"] = lookup[title]
            continue
        for t, a in lookup.items():
            if not a:
                continue
            if t.startswith(title[:12]) or title.startswith(t[:12]):
                g["author"] = a
                break
    return groups


class Handler(BaseHTTPRequestHandler):
    server_version = "KindleBridge/1.0"

    def log_message(self, fmt, *args):  # 静默日志
        pass

    # ---------- 基础响应工具 ----------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _download(self, filename: str, body: bytes, ctype: str):
        from urllib.parse import quote
        disp = f"attachment; filename=\"export\"; filename*=UTF-8''{quote(filename)}"
        self._send(200, body, ctype, {"Content-Disposition": disp})

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _same_origin(self) -> bool:
        """挡住其它网页对 127.0.0.1 的 CSRF 调用。

        浏览器一定会带 Origin；不带 Origin 的是本机脚本（curl 等），放行。
        """
        origin = self.headers.get("Origin") or ""
        if not origin:
            return True
        host = self.headers.get("Host") or ""
        o = urlparse(origin)
        return bool(o.scheme and o.netloc) and f"{o.scheme}://{o.netloc}" == f"http://{host}"

    # ---------- 路由 ----------
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path == "/favicon.ico":
            # 浏览器总会来要这个，给个 1x1 透明 PNG，省得控制台里挂一条 404
            return self._send(200, bytes.fromhex(
                "89504e470d0a1a0a0000000d494844520000000100000001080600000"
                "01f15c4890000000d4944415478da63fcffff3f0300050001a5f645bf"
                "0000000049454e44ae426082"), "image/png", {"Cache-Control": "max-age=86400"})
        if path == "/api/status":
            data = collect()
            return self._json({
                "device": data["device"], "calibre": data["calibre"],
                "zhconv": {"backend": hanzi_mod.backend(),
                           "available": hanzi_mod.available()},
                "tts": {"backend": tts_mod.backend(),
                        "available": tts_mod.available()},
            })
        if path == "/api/data":
            q = urlparse(self.path).query
            return self._json(collect(force="refresh=1" in q))
        if path == "/api/epub/state":
            return self._json(self._epub_state())
        if path == "/api/epub/inbox":
            return self._json({"inbox": INBOX_DIR, "files": self._epub_inbox()})
        if path == "/api/calibre/state":
            q = urlparse(self.path).query
            return self._json(self._calibre_state(force="force=1" in q))
        if path == "/api/calibre/progress":
            return self._json(cal_mod.progress())
        if path == "/api/free/search":
            return self._free_search(urlparse(self.path).query)
        if path == "/api/free/state":
            return self._json(free_mod.state())
        if path == "/api/device/dupes":
            dev = dev_mod.find_kindle()
            return self._json(deliv_mod.device_duplicates(dev.documents if dev else ""))
        if path == "/api/classics/state":
            return self._json(cls_mod.status())
        if path == "/api/tts/voices":
            return self._json(tts_mod.list_voices())
        if path == "/api/reader/shelf":
            return self._json(reader_mod.scan_shelf())
        if path == "/api/reader/meta":
            return self._reader_meta(urlparse(self.path).query)
        if path == "/api/reader/epub":
            return self._reader_epub(urlparse(self.path).query)
        m_book = re.match(r"^/api/reader/book/([0-9a-f]{16})\.epub$", path)
        if m_book:
            return self._reader_epub("key=" + m_book.group(1))
        if path == "/api/reader/cover":
            return self._reader_cover(urlparse(self.path).query)
        if path == "/api/dict/lookup":
            return self._dict_lookup(urlparse(self.path).query)
        return self._static(path.lstrip("/"))

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = unquote(urlparse(self.path).path)

        # 上传走原始字节流，必须在解析 JSON 之前处理
        if path == "/api/epub/upload":
            return self._epub_upload()

        # 简繁转换：原始字节上传（浏览器拖拽的文件）
        if path == "/api/zh-convert":
            return self._zh_convert_upload()

        payload = self._read_json()

        if path == "/api/export":
            data = collect()
            kind = payload.get("kind", "all")
            try:
                name, body, ctype = exp_mod.build_export(
                    kind, data["highlights"]["groups"], data["vocab"]["words"], data["device"])
            except ValueError as ex:
                return self._json({"error": str(ex)}, 400)
            return self._download(name, body, ctype)

        if path == "/api/books/export":
            return self._books_export(payload)

        if path == "/api/epub/inspect":
            return self._epub_inspect(payload)

        if path == "/api/epub/prepare":
            return self._epub_prepare(payload)

        if path == "/api/epub/eml":
            return self._epub_make_eml(payload)

        if path == "/api/epub/remove":
            return self._epub_remove(payload)

        if path == "/api/zh-convert/file":
            return self._zh_convert_file(payload)

        if path == "/api/calibre/download":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            return self._json(cal_mod.start_download(force=bool(payload.get("force"))))

        if path == "/api/calibre/cancel":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            return self._json(cal_mod.cancel_download())

        if path == "/api/calibre/reveal":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            return self._json(cal_mod.reveal_installer())

        if path == "/api/calibre/run":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            if not payload.get("confirm"):
                return self._json({"error": "需要显式确认才会启动安装向导"}, 400)
            return self._json(cal_mod.run_installer())

        if path == "/api/calibre/redetect":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            return self._json(self._calibre_state(force=True))

        if path == "/api/open":
            target = payload.get("path") or OUT_DIR
            real = os.path.realpath(target)
            if os.path.commonpath([real, os.path.realpath(BASE_DIR)]) != os.path.realpath(BASE_DIR):
                return self._json({"error": "拒绝访问工作目录之外的路径"}, 403)
            return self._json({"ok": conv_mod.open_in_explorer(real)})

        if path == "/api/free/fetch":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            try:
                return self._json(free_mod.enqueue(payload.get("items") or [],
                                                   push=bool(payload.get("push"))))
            except free_mod.FreeError as ex:
                return self._json({"error": str(ex)}, 400)

        if path == "/api/free/cancel":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            return self._json(free_mod.cancel(payload.get("id") or ""))

        if path == "/api/free/retry":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            return self._json(free_mod.retry(payload.get("id") or ""))

        if path == "/api/free/clear":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            return self._json(free_mod.clear_finished())

        if path == "/api/classics/build":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            return self._classics_build(payload)

        if path == "/api/tts":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            return self._tts_synth(payload)

        if path == "/api/reader/progress":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            return self._json(reader_mod.save_progress(
                payload.get("key") or "", payload.get("percent") or 0,
                payload.get("cfi") or "", payload.get("chapter") or ""))

        if path == "/api/reader/annotations":
            if not self._same_origin():
                return self._json({"error": "拒绝跨站请求"}, 403)
            action = (payload.get("action") or "add").strip().lower()
            key = payload.get("key") or ""
            if action == "remove":
                return self._json({"ok": reader_mod.remove_annot(key, payload.get("id") or "")})
            return self._json(reader_mod.add_annot(
                key, payload.get("text") or "", payload.get("cfi") or "",
                payload.get("note") or "", payload.get("chapter") or ""))

        return self._json({"error": "not found"}, 404)

    def _classics_build(self, payload: dict):
        """把本地中文经典语料里的一本书排成 EPUB，再转 AZW3，可选直接送设备。

        和公版书库那套下载队列不是一回事：这里没有网络、没有分片、没有断点续传，
        整个过程是本地算的，所以做成同步接口，几秒就返回。
        """
        book_id = (payload.get("book_id") or "").strip()
        # 前端传的是书卡上的 url（形如 classic:book:论语/lunyu.json），这里容错掉前缀
        if book_id.startswith("classic:"):
            book_id = book_id[len("classic:"):]
        if not book_id:
            return self._json({"error": "没指定哪本书"}, 400)
        if not cls_mod.available():
            return self._json({"error": "本地中文语料还没下载，先跑 "
                                        "_tools/fetch-chinese-poetry.py"}, 400)

        target = (payload.get("target") or "azw3").strip().lower()
        want_push = bool(payload.get("push"))
        simplified = payload.get("simplified", True)

        try:
            made = cls_mod.build_epub(book_id, INBOX_DIR, simplified=bool(simplified))
        except KeyError as ex:
            return self._json({"error": str(ex)}, 400)
        except Exception as ex:                    # noqa: BLE001
            return self._json({"error": f"成书失败：{ex}"}, 400)
        if not made.get("ok"):
            return self._json({"error": made.get("error") or "成书失败"}, 400)

        out = {
            "ok": True, "book_id": book_id,
            "title": made.get("title", ""), "author": made.get("author", ""),
            "chapters": made.get("chapters", 0), "paras": made.get("paras", 0),
            "epub": made.get("out", ""),
        }

        if target == "epub":
            out["out"] = out["epub"]
            out["note"] = "已生成简体 EPUB，放在「收书」里"
            return self._json(out)

        converter = conv_mod.find_ebook_convert()
        if not converter:
            out["out"] = out["epub"]
            out["note"] = "没找到 Calibre，先给了 EPUB；装上 Calibre 后可转 AZW3"
            return self._json(out)

        steps = deliv_mod.to_azw3([out["epub"]], OUT_DIR, converter)
        if not steps or not steps[0].ok:
            return self._json({"error": (steps[0].message if steps else "转换失败")}, 400)

        out["azw3"] = steps[0].out
        out["out"] = steps[0].out
        out["note"] = steps[0].message

        if want_push:
            dev = dev_mod.find_kindle()
            psteps = deliv_mod.push_native([steps[0].out],
                                           dev.documents if dev else "", OUT_DIR)
            ps = psteps[0] if psteps else None
            out["push"] = {
                "ok": bool(ps and ps.ok),
                "message": ps.message if ps else "推送失败",
                "out": ps.out if ps else "",
            }
        return self._json(out)

    # ---------- 本地语音合成（Coqui TTS） ----------
    def _tts_synth(self, payload: dict):
        """把文字合成成语音，返回 WAV 字节。

        模型在首次使用某个声音时由 Coqui 自动下载（约 50~120 MB），之后缓存本地。
        没装 TTS 时返回清晰的安装提示，而不是 500。
        """
        if not tts_mod.available():
            return self._json({
                "error": "未安装 Coqui TTS。请先 pip install -r requirements-tts.txt "
                         "（需要 Python 3.9~3.11），然后重启本服务。",
            }, 400)

        text = (payload.get("text") or "").strip()
        if not text:
            return self._json({"error": "没有可朗读的文字"}, 400)
        if len(text) > 20000:
            return self._json({"error": "单次文字过长（上限 20000 字），请分段"}, 413)

        voice = payload.get("voice") or None
        try:
            info = tts_mod.synth(text, voice=voice)
        except tts_mod.TTSSError as ex:
            return self._json({"error": str(ex)}, 400)
        except Exception as ex:                    # noqa: BLE001
            return self._json({"error": f"语音合成失败：{ex}"}, 500)

        meta = {k: v for k, v in info.items() if k != "bytes"}
        from urllib.parse import quote
        fname = f"kindle-bridge-tts-{meta.get('voice', 'out')}.wav"
        self._send(200, info["bytes"], "audio/wav", {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}",
            "X-Tts-Meta": base64.urlsafe_b64encode(
                json.dumps(meta, ensure_ascii=False).encode("utf-8")).decode("ascii"),
        })

    def _books_export(self, payload: dict):
        data = collect()
        wanted = set(payload.get("files") or [])
        mode = payload.get("mode", "copy")
        target = payload.get("target", "azw3")
        books = [b for b in data["library"]["books"] if not wanted or b["file"] in wanted]
        if not books:
            return self._json({"error": "没有选中任何书籍"}, 400)

        out_dir = os.path.join(OUT_DIR, "微信读书")
        if mode == "convert":
            results = conv_mod.convert_books(books, target, out_dir)
        else:
            results = conv_mod.export_for_wechat(books, out_dir)
        return self._json({
            "ok": True,
            "out_dir": out_dir,
            "results": [r.to_dict() for r in results],
        })

    # ---------- Calibre 环境 ----------
    def _calibre_state(self, force: bool = False) -> dict:
        info = cal_mod.state(force=force)
        if force:
            # 目录/版本变了，让书库页的「用 Calibre 转换」也立刻跟上
            with _LOCK:
                _CACHE["at"] = 0.0
        return info

    # ---------- 公版书库 ----------
    def _free_search(self, query: str) -> None:
        from urllib.parse import parse_qs

        p = parse_qs(query)
        q = (p.get("q") or [""])[0]
        source = (p.get("source") or ["all"])[0]
        lang = (p.get("lang") or [""])[0]
        try:
            page = max(1, int((p.get("page") or ["1"])[0]))
        except ValueError:
            page = 1
        try:
            data = free_mod.search(q, source, lang, page)
        except free_mod.FreeError as ex:
            return self._json({"error": str(ex)}, 502)
        data["sources"] = free_mod.SOURCES
        data["langs"] = free_mod.LANGS
        data["inbox"] = free_mod.INBOX_DIR
        return self._json(data)

    # ---------- EPUB 投递 ----------
    def _device_documents(self) -> str:
        dev = dev_mod.find_kindle()
        return dev.documents if dev else ""

    def _epub_state(self) -> dict:
        info = deliv_mod.route_info(self._device_documents())
        info["inbox"] = INBOX_DIR
        info["out"] = {
            "kindle": os.path.join(OUT_DIR, "Kindle书"),
            "send": os.path.join(OUT_DIR, "SendToKindle"),
            "koreader": os.path.join(OUT_DIR, "KOReader书库"),
        }
        return info

    def _epub_inbox(self) -> list[dict]:
        items: list[dict] = []
        if not os.path.isdir(INBOX_DIR):
            return items
        for name in sorted(os.listdir(INBOX_DIR)):
            if not name.lower().endswith(INBOX_EXTS):
                continue
            full = os.path.join(INBOX_DIR, name)
            if not os.path.isfile(full):
                continue
            st = os.stat(full)
            items.append({
                "name": name,
                "size": st.st_size,
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
            })
        return items

    def _epub_path(self, name: str) -> str | None:
        """把前端传进来的文件名解析成 INBOX 内的绝对路径，越界一律拒绝。"""
        if not name:
            return None
        if os.path.basename(name) != name or ":" in name or "/" in name or "\\" in name:
            return None
        full = os.path.realpath(os.path.join(INBOX_DIR, name))
        if os.path.commonpath([full, os.path.realpath(INBOX_DIR)]) != os.path.realpath(INBOX_DIR):
            return None
        return full

    def _epub_selection(self, payload: dict) -> tuple[list[str], list[str]]:
        names = payload.get("files")
        if not names:
            names = [i["name"] for i in self._epub_inbox()]
        paths, bad = [], []
        for n in names:
            p = self._epub_path(n)
            (paths if p and os.path.isfile(p) else bad).append(p if p and os.path.isfile(p) else n)
        return paths, bad

    def _epub_upload(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json({"error": "长度无效"}, 400)
        if length <= 0:
            return self._json({"error": "空文件"}, 400)
        if length > 300 * 1024 * 1024:
            return self._json({"error": "单个文件过大（上限 300 MB）"}, 413)

        raw_name = self.headers.get("X-Filename") or ""
        try:
            name = base64.urlsafe_b64decode(raw_name + "===").decode("utf-8")
        except Exception:
            return self._json({"error": "文件名编码无效"}, 400)

        name = epub_mod.safe_filename(name, 120)
        if not name.lower().endswith(INBOX_EXTS):
            return self._json({"error": "只接受 " + " / ".join(INBOX_EXTS) + " 文件"}, 400)

        os.makedirs(INBOX_DIR, exist_ok=True)
        target = os.path.join(INBOX_DIR, name)
        base, ext = os.path.splitext(name)
        n = 2
        while os.path.exists(target):
            target = os.path.join(INBOX_DIR, f"{base} ({n}){ext}")
            n += 1

        remaining = length
        try:
            with open(target, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(1024 * 512, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
        except OSError as ex:
            return self._json({"error": f"保存失败：{ex}"}, 500)
        if remaining > 0:
            return self._json({"error": "上传中断"}, 400)
        return self._json({"ok": True, "name": os.path.basename(target)})

    def _epub_inspect(self, payload: dict):
        paths, bad = self._epub_selection(payload)
        reports = []
        for p in paths:
            try:
                reports.append(deliv_mod.inspect_any(p))
            except Exception as ex:                       # 单个文件失败不拖垮整批
                rep = {"path": p, "name": os.path.basename(p), "kind": "unknown", "valid": False,
                       "issues": [{"msg": f"解析异常：{ex}", "fix": ""}], "warnings": [], "notes": []}
                reports.append(rep)
        return self._json({"ok": True, "reports": reports, "missing": bad})

    def _epub_prepare(self, payload: dict):
        paths, bad = self._epub_selection(payload)
        if not paths:
            return self._json({"error": "「收书」文件夹里还没有 EPUB"}, 400)

        mode = payload.get("mode", "clean")
        push = bool(payload.get("push"))
        state = self._epub_state()
        documents = state["device_documents"]

        if mode == "azw3":
            out_dir = state["out"]["kindle"]
            steps = deliv_mod.to_azw3(paths, out_dir, state["calibre"])
        elif mode == "koreader":
            out_dir = state["out"]["koreader"]
            steps = deliv_mod.stage_koreader(paths, out_dir)
        elif mode == "native":
            # MOBI 家族：设备原生可读，直接拷进去 —— 这一步不需要任何转换
            out_dir = state["out"]["kindle"]
            steps = deliv_mod.push_native(paths, documents, out_dir)
            push = False          # 已经直投过了，不再走二次复制
            if documents and os.path.isdir(documents):
                out_dir = documents
        else:
            out_dir = state["out"]["send"]
            steps = deliv_mod.clean_epubs(paths, out_dir)

        pushed: list[dict] = []
        if push:
            made = [s.out for s in steps if s.ok and s.out]
            pushed = [s.to_dict() for s in deliv_mod.push_to_device(made, documents)]

        return self._json({
            "ok": True,
            "mode": mode,
            "out_dir": out_dir,
            "results": [s.to_dict() for s in steps],
            "pushed": pushed,
            "missing": bad,
        })

    def _epub_make_eml(self, payload: dict):
        p = self._epub_path(payload.get("file") or "")
        if not p or not os.path.isfile(p):
            return self._json({"error": "文件不在「收书」文件夹里"}, 400)
        if not p.lower().endswith(".epub"):
            return self._json({
                "error": "Send to Kindle 只收 EPUB（MOBI 已于 2023-12 起停止接收）。"
                         "MOBI 家族的文件直接拷进设备就能读，不必发邮件。",
            }, 400)
        to_addr = (payload.get("to") or "").strip()
        from_addr = (payload.get("from") or "").strip()
        out_dir = os.path.join(OUT_DIR, "SendToKindle")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, os.path.splitext(os.path.basename(p))[0] + ".eml")
        try:
            blob = epub_mod.make_eml(p, to_addr, from_addr)
            with open(out, "wb") as f:
                f.write(blob)
        except OSError as ex:
            return self._json({"error": f"生成失败：{ex}"}, 500)
        return self._json({"ok": True, "out": out, "out_name": os.path.basename(out),
                           "note": "双击这个 .eml 会用你的邮件客户端打开，附件已挂好，点发送即可"})

    def _epub_remove(self, payload: dict):
        names = payload.get("files") or []
        removed = []
        for n in names:
            p = self._epub_path(n)
            if p and os.path.isfile(p):
                try:
                    os.remove(p)
                    removed.append(n)
                except OSError:
                    pass
        return self._json({"ok": True, "removed": removed})

    # ---------- 简繁转换 ----------
    def _zh_prepare(self, direction: str):
        """把前端传的方向参数归一成 zhconv_file 接受的取值，并校验。"""
        d = (direction or "auto").strip().lower()
        if d in ("auto", "simplified", "traditional", "简体", "繁体", "simp", "trad"):
            return d
        return "auto"

    def _zh_serve(self, out_path: str, out_name: str):
        """读转换产物，作为下载附件返回。"""
        try:
            with open(out_path, "rb") as f:
                body = f.read()
        except OSError as ex:
            return self._json({"error": f"读取结果失败：{ex}"}, 500)
        ctype = {
            ".epub": "application/epub+zip",
            ".txt": "text/plain; charset=utf-8",
        }.get(os.path.splitext(out_path)[1].lower(), "application/octet-stream")
        self._download(out_name, body, ctype)

    def _zh_inbox_copy(self, out_path: str, out_name: str) -> str | None:
        """把结果同时放进「收书」，方便后续投递到设备。返回落地文件名或 None。"""
        base, ext = os.path.splitext(epub_mod.safe_filename(out_name, 110))
        n = 2
        target = os.path.join(INBOX_DIR, f"{base}{ext}")
        while os.path.exists(target):
            target = os.path.join(INBOX_DIR, f"{base} ({n}){ext}")
            n += 1
        try:
            with open(out_path, "rb") as f:
                data = f.read()
            with open(target, "wb") as f:
                f.write(data)
            return os.path.basename(target)
        except OSError:
            return None

    def _zh_convert_upload(self):
        """拖拽上传 → 转换 → 直接下载；可选 X-Inbox=1 同时落「收书」。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json({"error": "长度无效"}, 400)
        if length <= 0:
            return self._json({"error": "空文件"}, 400)
        if length > 300 * 1024 * 1024:
            return self._json({"error": "单个文件过大（上限 300 MB）"}, 413)

        raw_name = self.headers.get("X-Filename") or ""
        try:
            name = base64.urlsafe_b64decode(raw_name + "===").decode("utf-8")
        except Exception:
            name = "upload.bin"
        name = epub_mod.safe_filename(name, 110)
        direction = self._zh_prepare(self.headers.get("X-Direction") or "auto")
        want_inbox = (self.headers.get("X-Inbox") or "").strip() == "1"

        tmp = os.path.join(OUT_DIR, "简繁转换")
        os.makedirs(tmp, exist_ok=True)
        src = os.path.join(tmp, name)
        base, ext = os.path.splitext(name)
        n = 2
        while os.path.exists(src):
            src = os.path.join(tmp, f"{base} ({n}){ext}")
            n += 1
        try:
            with open(src, "wb") as f:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(1024 * 512, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
        except OSError as ex:
            return self._json({"error": f"保存失败：{ex}"}, 500)
        if remaining > 0:
            return self._json({"error": "上传中断"}, 400)

        out = os.path.join(tmp, f"{base}.conv{ext}")
        res = zcf_mod.zhconv_file(src, out, direction)
        if not res.get("ok"):
            return self._json({"error": res.get("error") or "转换失败"}, 400)

        inbox_name = None
        if want_inbox:
            inbox_name = self._zh_inbox_copy(out, name)

        out_name = name
        meta = {k: v for k, v in res.items() if k not in ("ok", "out")}
        meta["inbox"] = inbox_name
        if inbox_name:
            meta["note"] = "已转换并放入「收书」，可在 EPUB 标签页投递到设备"
        # 元信息塞进响应头，前端读取（方向、编码、改动等）
        from urllib.parse import quote
        self._send(200, self._zh_body(out),
                   "application/epub+zip" if out_name.lower().endswith(".epub")
                   else "text/plain; charset=utf-8",
                   {"Content-Disposition":
                    f"attachment; filename*=UTF-8''{quote(out_name)}",
                    "X-Zh-Meta": base64.urlsafe_b64encode(
                        json.dumps(meta, ensure_ascii=False).encode("utf-8")).decode("ascii")})

    def _zh_body(self, out_path: str) -> bytes:
        with open(out_path, "rb") as f:
            return f.read()

    def _zh_convert_file(self, payload: dict):
        """转换「收书」里已存在的某个文件（避免重复上传）。"""
        name = payload.get("file") or ""
        p = self._epub_path(name)
        if not p or not os.path.isfile(p):
            return self._json({"error": "文件不在「收书」文件夹里"}, 400)
        direction = self._zh_prepare(payload.get("direction") or "auto")

        tmp = os.path.join(OUT_DIR, "简繁转换")
        os.makedirs(tmp, exist_ok=True)
        base, ext = os.path.splitext(os.path.basename(p))
        out = os.path.join(tmp, f"{base}.conv{ext}")
        res = zcf_mod.zhconv_file(p, out, direction)
        if not res.get("ok"):
            return self._json({"error": res.get("error") or "转换失败"}, 400)
        self._zh_serve(out, os.path.basename(p))

    # ---------- 本地阅读器 ----------
    def _reader_key(self, query: str) -> str:
        from urllib.parse import parse_qs
        return (parse_qs(query).get("key") or [""])[0]

    def _reader_meta(self, query: str):
        """一本书的阅读信息：元信息、封面、上次读到哪、已有哪些标注。

        这里**不做**转换 —— TXT 现打包、MOBI 走 Calibre 都慢，留给 /api/reader/epub
        那一跳（前端在“打开书”时才可能等），meta 始终秒回。
        """
        key = self._reader_key(query)
        path = reader_mod.resolve_path(key)
        if not path:
            return self._json({"error": "没找到这本书（可能已移走，点「刷新书架」再试）"}, 404)
        m = reader_mod.meta(path)
        ext = os.path.splitext(path)[1].lower()
        has_cover = bool(reader_mod.cover_cached(path, key))
        out = {
            "ok": True, "key": key, "title": m["title"], "author": m["author"],
            "drm": m["drm"], "ext": ext,
            "needs_convert": ext != ".epub",
            "cover": f"/api/reader/cover?key={key}" if has_cover else "",
            # 关键：epub.js 靠 URL 后缀判断「打包文件」还是「散装目录」。
            # 结尾不是 .epub 时它会当成散装目录，去请求 <基址>/META-INF/container.xml
            # （这里就成了 /api/reader/META-INF/container.xml）→ 404 → 白屏。
            # 所以给阅读器一条以 .epub 结尾的地址；epub_url 留给「下载」用。
            "book_url": f"/api/reader/book/{key}.epub",
            "epub_url": f"/api/reader/epub?key={key}",
            "last": reader_mod.load_progress().get(key) or {},
            "annotations": reader_mod.annots_of(key),
        }
        if ext not in (".epub", ".txt", ".text", ".md"):
            # MOBI 家族要外调 Calibre，先把“能不能转”说清楚，别等用户点了才报错
            out["converter"] = "calibre"
            out["converter_ok"] = bool(conv_mod.find_ebook_convert())
        if m["drm"]:
            out["warning"] = "这本书带 DRM，很可能读不出来。本工具不做任何破解。"
        return self._json(out)

    def _reader_epub(self, query: str):
        """把书变成 epub.js 能直接读的 EPUB 字节。TXT 现打包、MOBI 走 Calibre。"""
        key = self._reader_key(query)
        path = reader_mod.resolve_path(key)
        if not path:
            return self._json({"error": "没找到这本书"}, 404)
        ready = reader_mod.ensure_readable(path)
        if not ready.get("ok"):
            return self._json({"error": ready.get("error") or "无法准备这本书"}, 400)
        try:
            with open(ready["path"], "rb") as f:
                body = f.read()
        except OSError as ex:
            return self._json({"error": f"读取失败：{ex}"}, 500)
        self._send(200, body, "application/epub+zip", {
            "X-Reader-Note": "mobi" if ready.get("converted") else "direct",
        })

    def _reader_cover(self, query: str):
        key = self._reader_key(query)
        path = reader_mod.resolve_path(key)
        if not path:
            return self._send(404, b"not found", "text/plain")
        got = reader_mod.cover_cached(path, key)
        if not got:
            return self._send(404, b"no cover", "text/plain")
        cover_path, ctype = got
        try:
            with open(cover_path, "rb") as f:
                body = f.read()
        except OSError:
            return self._send(404, b"no cover", "text/plain")
        self._send(200, body, ctype, {"Cache-Control": "max-age=3600"})

    def _dict_lookup(self, query: str):
        from urllib.parse import parse_qs
        q = (parse_qs(query).get("q") or [""])[0].strip()
        res = dictdata_mod.lookup(q)
        self._json(res)

    def _static(self, rel: str):
        rel = rel.split("?")[0].lstrip("/")
        if not rel or rel.endswith("/"):
            rel += "index.html"
        safe = posixpath.normpath(rel).replace("\\", "/")
        if safe.startswith("../") or safe.startswith("/") or ":" in safe:
            return self._send(403, b"forbidden", "text/plain")
        full = os.path.join(WEB_DIR, *safe.split("/"))
        if not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)


def _bridge_alive(url: str) -> bool:
    """看看占着端口的那个进程是不是一个健康的 Kindle 桥。"""
    try:
        import urllib.request
        with urllib.request.urlopen(url + "api/status", timeout=3) as f:
            return "device" in json.loads(f.read().decode("utf-8", "ignore"))
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description="Kindle 桥")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(INBOX_DIR, exist_ok=True)
    url = f"http://{args.host}:{args.port}/"
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as ex:
        if _bridge_alive(url):
            # 双击 bat 时最常见：之前的服务还活着。别报错，直接把页面打开就完事。
            print(f"端口 {args.port} 上已有 Kindle 桥在运行，直接打开页面。")
            print("（想重启服务，请先结束旧的 python 进程，或直接重启电脑后先开 bat。）")
            if not args.no_browser:
                webbrowser.open(url)
            return
        for p in range(args.port + 1, args.port + 21):
            try:
                httpd = ThreadingHTTPServer((args.host, p), Handler)
                url = f"http://{args.host}:{p}/"
                print(f"注意：端口 {args.port} 被其他程序占用，已改用 {p}。")
                break
            except OSError:
                continue
        else:
            print(f"无法绑定端口 {args.port}（{ex}），且 8766~8785 都不可用。")
            return
    print(f"Kindle 桥已启动：{url}")
    print("按 Ctrl+C 停止。")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
