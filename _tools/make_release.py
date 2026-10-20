# -*- coding: utf-8 -*-
"""打一个可以直接发给别人的发布包（zip）。

打什么：
  源码（app.py / kindle / web / _test / _tools）+ 依赖清单 + 文档 + 启动器
不打什么：
  用户的私有数据与缓存 —— 导出/ 收书/ 工具/ corpus/ 以及 __pycache__。
  这些动辄几百 MB，而且是使用者自己的书，不该进版本库也不该跟着发布包走。

用法：
    python _tools/make_release.py                # 生成 _release/kindle-bridge-<版本>.zip
    python _tools/make_release.py --out D:\\tmp  # 指定输出目录
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 整个目录收进去的
INCLUDE_DIRS = ("kindle", "web", "_test", "_tools", "miniprogram")
# 整个目录收进去的单个文件
INCLUDE_FILES = (
    "app.py", "requirements.txt", "README.md", "LICENSE",
    ".gitignore", "start.sh", "启动 Kindle桥.bat",
)
# 发布包里要保留的空目录（放 .gitkeep 顶上）
EMPTY_DIRS = ("收书", "导出", "工具")
# 任何情况下都不收的
SKIP_NAMES = {"__pycache__", ".git", ".venv", "venv", ".pytest_cache", ".idea", ".vscode"}
SKIP_SUFFIX = (".pyc", ".pyo", ".log", ".err", ".epub", ".mobi", ".azw", ".azw3", ".prc", ".msi")


def _version() -> str:
    """版本号：优先读 VERSION 文件，其次读 README 里 version: 行，都没有就用今天日期。"""
    vf = os.path.join(ROOT, "VERSION")
    if os.path.isfile(vf):
        with open(vf, encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return v
    rd = os.path.join(ROOT, "README.md")
    if os.path.isfile(rd):
        with open(rd, encoding="utf-8") as f:
            for line in f:
                if line.startswith("version:"):
                    return line.split(":", 1)[1].strip()
    return date.today().isoformat()


def _collect():
    """列出要打进包里的文件（相对 ROOT 的路径）。"""
    items: list[str] = []
    for d in INCLUDE_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
            for fn in filenames:
                if fn.endswith(SKIP_SUFFIX) or fn == ".gitkeep":
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                items.append(rel)
    for fn in INCLUDE_FILES:
        if os.path.isfile(os.path.join(ROOT, fn)):
            items.append(fn)
    return sorted(set(items))


def build(out_dir: str | None = None) -> str:
    out_dir = out_dir or os.path.join(ROOT, "_release")
    os.makedirs(out_dir, exist_ok=True)
    ver = _version()
    name = f"kindle-bridge-{ver}"
    zip_path = os.path.join(out_dir, name + ".zip")

    items = _collect()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in items:
            z.write(os.path.join(ROOT, rel), os.path.join(name, rel))
        # 空目录用 .gitkeep 顶上，解压后目录就在，不会因为缺目录报错
        for d in EMPTY_DIRS:
            z.writestr(os.path.join(name, d, ".gitkeep"), "")

    size = os.path.getsize(zip_path)
    with zipfile.ZipFile(zip_path) as z:
        n = len(z.namelist())
    print(f"发布包已生成：{zip_path}")
    print(f"  文件数 {n}，体积 {size / 1024 / 1024:.2f} MB")
    print(f"  内容：{', '.join(INCLUDE_DIRS)} + {', '.join(INCLUDE_FILES)}")
    print(f"  已排除：导出/ 收书/ 工具/ corpus/ __pycache__ 等用户数据与缓存")
    return zip_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="生成 Kindle 桥发布包")
    ap.add_argument("--out", default=None, help="输出目录（默认 _release/）")
    a = ap.parse_args()
    build(a.out)
