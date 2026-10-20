# -*- coding: utf-8 -*-
"""书籍导出与格式转换。

- 微信读书直接支持的格式：复制到导出目录，清理文件名后即可上传。
- 其余格式：若系统安装了 Calibre，则调用 ebook-convert 转换。
  带 DRM 的文件不做任何破解，仅给出提示。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

from .library import WECHAT_SUPPORTED

ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str, max_len: int = 80) -> str:
    name = ILLEGAL.sub("_", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "untitled"


def find_ebook_convert() -> str | None:
    """查找 Calibre 的 ebook-convert。"""
    exe = "ebook-convert.exe" if os.name == "nt" else "ebook-convert"
    found = shutil.which(exe) or shutil.which("ebook-convert")
    if found:
        return found
    candidates = []
    if os.name == "nt":
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        ):
            if base:
                candidates.append(os.path.join(base, "Calibre2", exe))
                candidates.append(os.path.join(base, "calibre", exe))
    else:
        candidates += ["/usr/bin/ebook-convert", "/usr/local/bin/ebook-convert",
                       "/Applications/calibre.app/Contents/MacOS/ebook-convert"]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


@dataclass
class ConvertResult:
    file: str
    ok: bool
    message: str
    out: str = ""

    def to_dict(self) -> dict:
        return {"file": self.file, "ok": self.ok, "message": self.message,
                "out": self.out, "out_name": os.path.basename(self.out) if self.out else ""}


def export_for_wechat(books: list[dict], out_dir: str) -> list[ConvertResult]:
    """把微信读书支持的书籍复制到 out_dir，文件名清理为「书名 - 作者.ext」。"""
    os.makedirs(out_dir, exist_ok=True)
    results: list[ConvertResult] = []
    for b in books:
        ext = b["ext"]
        name = b["file"]
        if ext not in WECHAT_SUPPORTED:
            results.append(ConvertResult(name, False,
                f"微信读书不支持 .{ext}；可先在 Kindle 端转成 azw3 或参考下方提示"))
            continue
        if b.get("drm") == "drm":
            results.append(ConvertResult(name, False, "含 DRM，未做任何处理，请使用正版渠道"))
            continue
        title = safe_filename(b.get("title") or b["stem"])
        author = safe_filename(b.get("author") or "")
        out_name = f"{title} - {author}.{ext}" if author else f"{title}.{ext}"
        out_path = os.path.join(out_dir, out_name)
        try:
            shutil.copy2(b["path"], out_path)
        except OSError as ex:
            results.append(ConvertResult(name, False, f"复制失败：{ex}"))
            continue
        note = "已复制，可直接上传微信读书"
        if ext == "pdf":
            note = "已复制；PDF 在微信读书中不可标注、体验一般"
        results.append(ConvertResult(name, True, note, out_path))
    return results


def convert_books(books: list[dict], target: str, out_dir: str,
                  converter: str | None = None) -> list[ConvertResult]:
    """用 Calibre 把书籍转换成 target 格式（azw3 / epub / mobi / txt）。"""
    converter = converter or find_ebook_convert()
    os.makedirs(out_dir, exist_ok=True)
    results: list[ConvertResult] = []

    for b in books:
        name = b["file"]
        if not converter:
            results.append(ConvertResult(name, False, "未检测到 Calibre（ebook-convert）"))
            continue
        if b.get("drm") == "drm":
            results.append(ConvertResult(name, False, "含 DRM，未做任何处理"))
            continue
        title = safe_filename(b.get("title") or b["stem"])
        out_name = f"{title}.{target}"
        out_path = os.path.join(out_dir, out_name)
        cmd = [converter, b["path"], out_path]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.SubprocessError) as ex:
            results.append(ConvertResult(name, False, f"调用 Calibre 失败：{ex}"))
            continue
        if proc.returncode == 0 and os.path.isfile(out_path):
            results.append(ConvertResult(name, True, f"已转换为 {target}", out_path))
        else:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            msg = tail[-1] if tail else "转换失败"
            results.append(ConvertResult(name, False, msg[:160]))
    return results


def open_in_explorer(path: str) -> bool:
    """在系统文件管理器中打开目录（仅本机使用）。"""
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except OSError:
        return False
