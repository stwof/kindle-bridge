# -*- coding: utf-8 -*-
"""Kindle 设备探测：在已挂载的盘符里找出 Kindle。"""
from __future__ import annotations

import json
import os
import shutil
import string
from dataclasses import dataclass, field


ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "gb18030", "latin-1")


def read_text(path: str, limit: int | None = None) -> str:
    """按常见编码依次尝试读取文本文件。"""
    for enc in ENCODINGS:
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read(limit) if limit else f.read()
        except (UnicodeDecodeError, LookupError):
            continue
        except OSError:
            return ""
    return ""


@dataclass
class Device:
    root: str
    name: str = "Amazon Kindle"
    version: str = ""
    total_bytes: int = 0
    free_bytes: int = 0
    calibre_managed: bool = False
    is_kindle: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def documents(self) -> str:
        return os.path.join(self.root, "documents")

    @property
    def system(self) -> str:
        return os.path.join(self.root, "system")

    @property
    def clippings(self) -> str:
        return os.path.join(self.documents, "My Clippings.txt")

    @property
    def vocab_db(self) -> str:
        return os.path.join(self.system, "vocabulary", "vocab.db")

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "name": self.name,
            "version": self.version,
            "total_bytes": self.total_bytes,
            "free_bytes": self.free_bytes,
            "used_bytes": max(self.total_bytes - self.free_bytes, 0),
            "calibre_managed": self.calibre_managed,
            "is_kindle": self.is_kindle,
            "has_clippings": os.path.isfile(self.clippings),
            "has_vocab": os.path.isfile(self.vocab_db),
        }


def probe_drive(root: str) -> Device | None:
    """判断某个盘符是不是 Kindle；不是则返回 None。"""
    if not os.path.isdir(root):
        return None
    docs = os.path.join(root, "documents")
    syst = os.path.join(root, "system")
    ver_file = os.path.join(syst, "version.txt")

    has_docs = os.path.isdir(docs)
    has_syst = os.path.isdir(syst)
    has_ver = os.path.isfile(ver_file)
    if not (has_ver or (has_docs and has_syst)):
        return None

    dev = Device(root=root, is_kindle=has_ver)
    if has_ver:
        dev.version = read_text(ver_file, limit=200).strip()

    di = os.path.join(root, "driveinfo.calibre")
    if os.path.isfile(di):
        dev.calibre_managed = True
        try:
            info = json.loads(read_text(di) or "{}")
            dev.name = info.get("device_name") or dev.name
        except (ValueError, TypeError):
            pass

    try:
        usage = shutil.disk_usage(root)
        dev.total_bytes, dev.free_bytes = usage.total, usage.free
    except OSError:
        pass
    return dev


def find_kindle() -> Device | None:
    """遍历盘符，返回第一个识别到的 Kindle。"""
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            if not os.path.exists(root):
                continue
        except OSError:
            continue
        dev = probe_drive(root)
        if dev and dev.is_kindle:
            return dev
    return None
