# -*- coding: utf-8 -*-
"""EPUB → Kindle 的三条投递路线。

A. 离线转码   EPUB → AZW3（Calibre）→ 直接拷进设备 documents/。不碰账号、不用联网。
B. 云端转码   校验/修复 EPUB → 生成待发邮件 or 打开 Send to Kindle 网页。
C. 原生阅读   把 EPUB 原样整理好，等越狱后交给 KOReader（它的渲染比系统原生好）。

两条贯穿所有路线的硬规矩：

  1. **不重复**：投递前先把设备上现有的书做成内容索引（大小 → sha256），
     只要内容已经存在，不管它叫什么名字，一律跳过。绝不靠文件名猜。
  2. **不送坏书**：每一份进设备的文件，都走「临时文件 → fsync → 校验 → 原子改名」，
     改名之前比对大小与 sha256，改名之后再过一遍结构体检。
     校验不过就当场撤下，宁可在电脑上失败，也不留一本打不开的书在 Kindle 里。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass

from . import epub as epub_mod
from . import hanzi as hanzi_mod
from . import integrity as int_mod
from . import mobi as mobi_mod
from .convert import find_ebook_convert

# Calibre 的输出配置：面向 6 吋 Kindle。kindle_pw 的图片尺寸在 PW1~PW4 上都安全。
OUTPUT_PROFILE = "kindle_pw"

# Kindle 原生就能读、拷进去就索引的格式（EPUB 不在其中，固件里没有它的渲染器）
NATIVE_EXTS = (".mobi", ".azw", ".azw3", ".prc", ".txt", ".pdf")
MOBI_EXTS = (".mobi", ".azw", ".azw3", ".prc")


def inspect_any(path: str) -> dict:
    """按文件头挑体检器：MOBI 家族（含 KFX）走 mobi 模块，其余按 EPUB 处理。"""
    if mobi_mod.sniff(path) in ("mobi", "kfx"):
        return mobi_mod.inspect_mobi(path)
    return epub_mod.inspect_epub(path)


def _drop(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _hard_issues(rep: dict) -> list[dict]:
    """体检报告里的硬伤（打不开的毛病），不含 DRM。

    加密是「谁能读」的问题，不是「文件坏没坏」的问题 ——
    个人买的加密书不能因为带了 DRM 就被判成损坏文件。
    """
    return [i for i in rep.get("issues", [])
            if not any(m in i.get("msg", "") for m in ("DRM", "加密"))]


# 设备索引要扫的扩展名。只认这些，避免把 .sdr 里的碎片、系统文件也扫进来。
SCAN_EXTS = frozenset({
    ".mobi", ".azw", ".azw3", ".azw8", ".prc", ".kfx", ".pdf",
    ".txt", ".epub", ".doc", ".docx", ".rtf",
})


class DeviceIndex:
    """Kindle 上现有藏书的内容索引，用来回答「这本书是不是已经有了」。

    只按文件名判断是不够的：同一本书在不同来源下叫法千差万别
    （`红楼梦.mobi` 与 `曹雪芹 - 红楼梦.mobi` 是同一本，文件名却毫无共同点）。
    所以这里按「大小 + sha256」建索引 —— 大小不同必定不同，大小相同才真算哈希，
    扫几百本书时实际需要动 CPU 的只有个位数。
    """

    MAX_DEPTH = 4        # Kindle 本来也不索引太深的目录，扫到 4 层足够
    MAX_FILES = 20000    # 兜底，防止有人把整个硬盘塞进 documents 把扫描拖死

    def __init__(self, documents_dir: str = ""):
        self.root = (documents_dir or "").rstrip("\\/")
        self.by_size: dict[int, list[str]] = {}
        self.paths: list[str] = []
        self.ready = False

    def build(self) -> "DeviceIndex":
        if not self.root or not os.path.isdir(self.root):
            return self
        base_len = len(self.root)
        for dirpath, dirnames, filenames in os.walk(self.root):
            if dirpath[base_len:].count(os.sep) >= self.MAX_DEPTH:
                dirnames[:] = []
            for fn in filenames:
                if len(self.paths) >= self.MAX_FILES:
                    return self._done()
                if fn.endswith(".kbtmp"):
                    continue
                if os.path.splitext(fn)[1].lower() not in SCAN_EXTS:
                    continue
                full = os.path.join(dirpath, fn)
                size, _ = int_mod.stat_of(full)
                if size <= 0:
                    continue
                self.paths.append(full)
                self.by_size.setdefault(size, []).append(full)
        return self._done()

    def _done(self) -> "DeviceIndex":
        self.ready = True
        return self

    def add(self, path: str) -> None:
        """投递成功后补进索引，同一批次里的重复也能被立刻发现。"""
        size, _ = int_mod.stat_of(path)
        if size <= 0:
            return
        self.paths.append(path)
        self.by_size.setdefault(size, []).append(path)

    def find_duplicate(self, path: str) -> str:
        """设备上有内容完全相同的书吗？有就返回它的路径，没有返回空串。"""
        size, _ = int_mod.stat_of(path)
        if size <= 0:
            return ""
        cands = self.by_size.get(size) or []
        if not cands:
            return ""
        try:
            want = int_mod.sha256_of(path)
        except int_mod.IntegrityError:
            return ""
        for c in cands:
            try:
                if int_mod.sha256_of(c) == want:
                    return c
            except int_mod.IntegrityError:
                continue
        return ""


def _next_free(dest_dir: str, name: str) -> tuple[str, bool]:
    """挑一个不撞车的落点。内容相同的已在去重阶段跳过，所以这里撞上的必定是另一本书。

    返回 (目标路径, 是否因为同名而改了名)。
    """
    stem, suffix = os.path.splitext(name)
    cand = os.path.join(dest_dir, name)
    n = 2
    renamed = False
    while os.path.exists(cand):
        cand = os.path.join(dest_dir, f"{stem} ({n}){suffix}")
        n += 1
        renamed = True
    return cand, renamed


def _deliver(src: str, target: str) -> tuple[int, str]:
    """把一份文件送进设备并当场验货。返回 (大小, 备注)；失败抛 IntegrityError。

    这是所有进设备路径的唯一出口 —— 复制、校验、复检三件事必须一起做，
    漏掉任何一件，都可能让一本打不开的书混进 Kindle。
    """
    size = int_mod.copy_verified(src, target)
    good, why = int_mod.check_openable(target)
    if not good:
        _drop(target)
        raise int_mod.IntegrityError(why)
    return size, why


@dataclass
class Step:
    file: str
    ok: bool
    message: str
    out: str = ""

    def to_dict(self) -> dict:
        return {
            "file": self.file, "ok": self.ok, "message": self.message,
            "out": self.out, "out_name": os.path.basename(self.out) if self.out else "",
        }


def route_info(documents_dir: str = "") -> dict:
    """当前机器上三条路线的可用状态。"""
    from . import calibre as cal_mod

    calibre = find_ebook_convert()
    inst = cal_mod.installer_info()
    return {
        "calibre": calibre or "",
        "calibre_ok": bool(calibre),
        "calibre_version": cal_mod.version_of(calibre) if calibre else "",
        "installer_ready": inst["ready"],
        "installer_name": inst["name"],
        "device_documents": documents_dir,
        "device_ok": bool(documents_dir and os.path.isdir(documents_dir)),
        "inbox_exts": [".epub", ".mobi", ".azw", ".azw3", ".prc"],
        "search_guide": [
            "打开 https://calibre-ebook.com/download_windows 下载安装包",
            "安装完成后回到本页点「重新检测」—— 无需重启工具",
            "若不想装软件，直接用路线 B（云端转码），效果同样可用",
        ],
    }


def _title_of(path: str, fallback: str) -> str:
    rep = inspect_any(path)
    name = (rep.get("title") or "").strip()
    if name:
        return epub_mod.safe_filename(name, 70)
    return epub_mod.safe_filename(fallback, 70)


def _unique(out_dir: str, stem: str, ext: str) -> str:
    """避免同名覆盖：标题相同的书依次落成「书名 (2).epub」。"""
    cand = os.path.join(out_dir, f"{stem}{ext}")
    n = 2
    while os.path.exists(cand):
        cand = os.path.join(out_dir, f"{stem} ({n}){ext}")
        n += 1
    return cand


def clean_epubs(paths: list[str], out_dir: str) -> list[Step]:
    """路线 B 前半段：结构体检 + 保守修复，产出可安全投递的 EPUB。"""
    os.makedirs(out_dir, exist_ok=True)
    steps: list[Step] = []
    for p in paths:
        name = os.path.basename(p)
        if not os.path.isfile(p):
            steps.append(Step(name, False, "文件不存在"))
            continue
        if not p.lower().endswith(".epub"):
            steps.append(Step(name, False, "这条路线只处理 EPUB；Kindle 原生格式请用「直接拷进设备」"))
            continue
        rep = epub_mod.inspect_epub(p)
        if rep["drm"]:
            steps.append(Step(name, False, "含 DRM，未做任何处理"))
            continue
        safe = _title_of(p, os.path.splitext(name)[0])
        out = _unique(out_dir, safe, ".epub")
        try:
            info = epub_mod.repair_epub(p, out)
        except (OSError, ValueError, zipfile.BadZipFile) as ex:
            steps.append(Step(name, False, f"修复失败：{ex}"))
            continue

        # 整理也是一次重写压缩包，产出的东西要回读一遍才算数
        bad = _hard_issues(epub_mod.inspect_epub(out))
        if bad:
            _drop(out)
            steps.append(Step(name, False, f"整理后的文件仍不可用，已删除：{bad[0]['msg']}"))
            continue

        detail = "；".join(info["changed"][:3])
        steps.append(Step(name, True, f"已整理：{detail}；结构复检通过", out))
    return steps


def to_azw3(paths: list[str], out_dir: str, converter: str = "",
            profile: str = OUTPUT_PROFILE) -> list[Step]:
    """路线 A：用 Calibre 把 EPUB 转成 AZW3。"""
    os.makedirs(out_dir, exist_ok=True)
    converter = converter or find_ebook_convert()
    steps: list[Step] = []

    for p in paths:
        name = os.path.basename(p)
        if not os.path.isfile(p):
            steps.append(Step(name, False, "文件不存在"))
            continue
        rep = inspect_any(p)
        if rep["drm"]:
            steps.append(Step(name, False, "含 DRM —— 转换的前提是不加密，本工具不做解密"))
            continue
        if not converter:
            steps.append(Step(name, False, "未检测到 Calibre，请先安装或改用路线 B"))
            continue
        target = _unique(out_dir, _title_of(p, os.path.splitext(name)[0]), ".azw3")
        cmd = [converter, p, target, "--output-profile", profile]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=900,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.SubprocessError) as ex:
            steps.append(Step(name, False, f"调用 Calibre 失败：{ex}"))
            continue
        if proc.returncode != 0 or not os.path.isfile(target):
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            steps.append(Step(name, False, (tail[-1] if tail else "转换失败")[:160]))
            continue

        # Calibre 偶尔会「返回码 0，产物却不可读」。光信返回码是不够的，
        # 必须把产物再体检一遍 —— 否则一个坏 AZW3 会被当成成功结果送进设备。
        bad = _hard_issues(mobi_mod.inspect_mobi(target))
        if bad:
            _drop(target)
            steps.append(Step(name, False, f"转换产物不可用，已删除：{bad[0]['msg']}"))
            continue

        size = os.path.getsize(target)
        steps.append(Step(name, True,
                          f"已转为 AZW3（{int_mod.size_text(size)}，结构复检通过）", target))
    return steps


def to_simplified_azw3(paths: list[str], out_dir: str, work_dir: str = "",
                       converter: str = "", profile: str = OUTPUT_PROFILE) -> list[Step]:
    """路线 A′：EPUB → 简体 EPUB → AZW3。

    古登堡的中文书几乎全是繁体（古典小说居多，多由港台或海外志愿者数字化）。
    Kindle 当然显示得了繁体，但一本 90 万字的《紅樓夢》看着就是累。
    这条路先把正文转成简体，再交给 Calibre 排成 AZW3。

    为什么必须经过 EPUB：MOBI 的正文是压缩的（PalmDOC / HUFF-CDIC），
    要改就得先解压再重压，风险和复杂度都不划算。EPUB 里的正文是明文 XHTML，
    改起来干净，而且它本来就在「EPUB → AZW3」这条必经之路上，顺路做掉。
    """
    os.makedirs(out_dir, exist_ok=True)
    converter = converter or find_ebook_convert()
    steps: list[Step] = []

    for p in paths:
        name = os.path.basename(p)
        if not os.path.isfile(p):
            steps.append(Step(name, False, "文件不存在"))
            continue
        if not p.lower().endswith(".epub"):
            steps.append(Step(name, False,
                              "繁转简只能在 EPUB 上做（MOBI 的正文是压缩的），请改用 EPUB 版本"))
            continue
        rep = epub_mod.inspect_epub(p)
        if rep["drm"]:
            steps.append(Step(name, False, "含 DRM，不能转换"))
            continue
        if not hanzi_mod.available():
            steps.append(Step(name, False, "简繁数据表缺失，无法转换"))
            continue

        stem = hanzi_mod.to_simplified(_title_of(p, os.path.splitext(name)[0]))
        tmpdir = tempfile.mkdtemp(prefix="kb-t2s-", dir=work_dir or None)
        try:
            mid = os.path.join(tmpdir, "simplified.epub")
            info = epub_mod.to_simplified_epub(p, mid)

            # 没有 Calibre 就停在简体 EPUB —— 半程成果也比没有强，
            # 用户可以自己走路线 B 发给 Kindle
            if not converter:
                target = _unique(out_dir, stem, ".epub")
                int_mod.copy_verified(mid, target)
                changed = "；".join(info["changed"][:2])
                steps.append(Step(name, True,
                                  f"已转简体（{changed}）；未装 Calibre，停在 EPUB",
                                  target))
                continue

            target = _unique(out_dir, stem, ".azw3")
            cmd = [converter, mid, target, "--output-profile", profile]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=900,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except (OSError, subprocess.SubprocessError) as ex:
                steps.append(Step(name, False, f"调用 Calibre 失败：{ex}"))
                continue
            if proc.returncode != 0 or not os.path.isfile(target):
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()
                steps.append(Step(name, False, (tail[-1] if tail else "转换失败")[:160]))
                continue

            bad = _hard_issues(mobi_mod.inspect_mobi(target))
            if bad:
                _drop(target)
                steps.append(Step(name, False, f"转换产物不可用，已删除：{bad[0]['msg']}"))
                continue

            size = os.path.getsize(target)
            steps.append(Step(name, True,
                              f"已转简体 AZW3（{int_mod.size_text(size)}，结构复检通过）", target))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return steps


def stage_koreader(paths: list[str], out_dir: str) -> list[Step]:
    """路线 C：把 EPUB 原样整理好，供越狱后的 KOReader 直接读取。"""
    os.makedirs(out_dir, exist_ok=True)
    steps: list[Step] = []
    for p in paths:
        name = os.path.basename(p)
        if not os.path.isfile(p):
            steps.append(Step(name, False, "文件不存在"))
            continue
        if not p.lower().endswith(".epub"):
            steps.append(Step(name, False, "KOReader 路线目前只整理 EPUB"))
            continue
        rep = epub_mod.inspect_epub(p)
        if rep["drm"]:
            steps.append(Step(name, False, "含 DRM，KOReader 同样打不开"))
            continue
        out = _unique(out_dir, _title_of(p, os.path.splitext(name)[0]), ".epub")
        try:
            int_mod.copy_verified(p, out)
            good, why = int_mod.check_openable(out)
            if not good:
                _drop(out)
                steps.append(Step(name, False, f"整理后校验没过，已删除：{why}"))
                continue
        except int_mod.IntegrityError as ex:
            _drop(out)
            steps.append(Step(name, False, f"整理失败：{ex}"))
            continue
        steps.append(Step(name, True,
                          f"已整理（{why}），拷到设备 documents/ 后由 KOReader 打开", out))
    return steps


def push_native(paths: list[str], documents_dir: str, fallback_dir: str) -> list[Step]:
    """路线 D：Kindle 原生格式直接拷进去，全程不做任何转换。

    这是 MOBI 家族最省事的路径 —— 它们本来就是亚马逊自家的格式，
    设备会直接索引，能查词、能标注，和商店买的书一视同仁。
    """
    os.makedirs(fallback_dir, exist_ok=True)
    on_device = bool(documents_dir and os.path.isdir(documents_dir))
    dest_dir = documents_dir if on_device else fallback_dir
    os.makedirs(dest_dir, exist_ok=True)

    # 只在真连上设备时才建索引 —— 没有设备就谈不上重复
    index = DeviceIndex(documents_dir).build() if on_device else None

    steps: list[Step] = []
    for p in paths:
        name = os.path.basename(p)
        if not os.path.isfile(p):
            steps.append(Step(name, False, "文件不存在"))
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext == ".epub":
            steps.append(Step(name, False, "EPUB 不在 Kindle 的原生格式里，请走路线 A 或 B"))
            continue
        if ext not in NATIVE_EXTS:
            steps.append(Step(name, False, f"Kindle 原生不认 {ext or '无扩展名'} 这个格式"))
            continue

        rep = inspect_any(p)
        src_bad = _hard_issues(rep)
        if src_bad:
            steps.append(Step(name, False, "源文件本身就有问题，不往设备里送：" + src_bad[0]["msg"]))
            continue

        # ---- 第一关：设备上是不是已经有这本了？（比内容，不比文件名）----
        if index:
            dup = index.find_duplicate(p)
            if dup:
                rel = os.path.relpath(dup, documents_dir)
                steps.append(Step(name, True,
                                  f"Kindle 里已经有这本了（{rel}），跳过，没有重复拷贝", dup))
                continue

        # ---- 第二关：放得下吗？ ----
        need, _ = int_mod.stat_of(p)
        lack = int_mod.ensure_space(dest_dir, need)
        if lack:
            steps.append(Step(name, False, lack))
            continue

        # ---- 第三关：落点不能撞掉设备上已有的另一本书 ----
        target, renamed = _next_free(dest_dir, name)

        try:
            size, why = _deliver(p, target)
        except int_mod.IntegrityError as ex:
            steps.append(Step(name, False, f"送进设备后校验没过，已撤下：{ex}"))
            continue

        if index:
            index.add(target)

        if on_device:
            msg = f"已放进 Kindle 的 documents/（{int_mod.size_text(size)}，{why}），拔线后即可在书库看到"
            if renamed:
                msg += f"；设备里已有一份同名的不同文件，这本存为「{os.path.basename(target)}」"
            if rep.get("drm"):
                msg += "（含 DRM，只有授权设备能打开）"
        else:
            msg = "未检测到 Kindle，已放到导出目录；连上设备后拖进 documents/ 即可"
        steps.append(Step(name, True, msg, target))
    return steps


def device_duplicates(documents_dir: str) -> dict:
    """扫一遍设备上现有的书，把内容完全相同的重复组找出来。

    只读，不动任何文件。用来回答「我 Kindle 里现在有没有重复」——
    去重逻辑管的是以后不会再混进去，这个管的是清理历史遗留。
    """
    idx = DeviceIndex(documents_dir).build()
    groups: dict[str, list[str]] = {}
    for size, paths in idx.by_size.items():
        if len(paths) < 2:
            continue                       # 大小就独一份，不可能是重复
        for p in paths:
            try:
                groups.setdefault(int_mod.sha256_of(p), []).append(p)
            except int_mod.IntegrityError:
                continue                   # 读不动的文件跳过，不因此中断整次扫描

    dupes = []
    for paths in groups.values():
        if len(paths) < 2:
            continue
        size = int_mod.stat_of(paths[0])[0]
        paths.sort(key=lambda p: (p.count(os.sep), len(p)))
        dupes.append({
            "size": size,
            "waste": size * (len(paths) - 1),      # 留一份，其余都是白占的空间
            "files": [os.path.relpath(p, documents_dir) for p in paths],
        })
    dupes.sort(key=lambda d: d["waste"], reverse=True)

    return {
        "ok": bool(documents_dir and os.path.isdir(documents_dir)),
        "scanned": len(idx.paths),
        "groups": dupes,
        "wasted": sum(d["waste"] for d in dupes),
        "wasted_text": int_mod.size_text(sum(d["waste"] for d in dupes)),
    }


def push_to_device(paths: list[str], documents_dir: str) -> list[Step]:
    """把已经产出的文件直接拷进 Kindle 的 documents/。

    和 push_native 共用同一套规矩：先查重、再问空间、最后复制并验货。
    以前这里是「同名就覆盖」—— 设备上已有的同名文件会被悄无声息地换掉，
    现在改成绝不覆盖，撞名就另起一个名字。
    """
    steps: list[Step] = []
    if not documents_dir or not os.path.isdir(documents_dir):
        return [Step(os.path.basename(p), False, "未检测到 Kindle 的 documents 目录") for p in paths]

    index = DeviceIndex(documents_dir).build()
    for p in paths:
        name = os.path.basename(p)
        if not os.path.isfile(p):
            steps.append(Step(name, False, "文件不存在"))
            continue

        dup = index.find_duplicate(p)
        if dup:
            rel = os.path.relpath(dup, documents_dir)
            steps.append(Step(name, True,
                              f"Kindle 里已经有这本了（{rel}），跳过，没有重复拷贝", dup))
            continue

        need, _ = int_mod.stat_of(p)
        lack = int_mod.ensure_space(documents_dir, need)
        if lack:
            steps.append(Step(name, False, lack))
            continue

        target, renamed = _next_free(documents_dir, name)
        try:
            size, why = _deliver(p, target)
        except int_mod.IntegrityError as ex:
            steps.append(Step(name, False, f"送进设备后校验没过，已撤下：{ex}"))
            continue

        index.add(target)
        msg = f"已放入 Kindle documents/（{int_mod.size_text(size)}，{why}），拔线后即可在书库看到"
        if renamed:
            msg += f"；设备里已有一份同名的不同文件，这本存为「{os.path.basename(target)}」"
        steps.append(Step(name, True, msg, target))
    return steps
