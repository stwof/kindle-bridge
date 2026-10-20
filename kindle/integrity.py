# -*- coding: utf-8 -*-
"""投递完整性底座 —— 内容指纹、可校验复制、结构复检、空间预检。

这个文件只回答三个问题，别的都不管：

  1. 这两份文件是不是同一本书？（去重靠它）
  2. 我刚拷过去的这份，跟源文件一模一样吗？结构还能打开吗？（完整性靠它）
  3. 设备上还放得下吗？（空间靠它）

为什么要单独拆出来：投递链路上的每一步（下载落盘、格式转换、拷进设备）
都可能悄悄产出一份「看起来是书、实际打不开」的文件。Kindle 的阅读器对坏文件
很不宽容 —— 一个残缺的 MOBI 会让它卡在索引阶段，或者干脆不显示。
所以宁可在电脑上校验失败，也不要把坏文件送进设备。

设计取舍：
  · 指纹分两层：先比大小（不同必不同，零成本），大小相同才真算 sha256。
    扫几百本书时几乎只有个位数需要动 CPU。
  · 复制走「临时文件 → fsync → 校验 → 原子改名」，绝不留下半个文件。
    Windows 上 copy 返回不代表数据落盘，拔线丢尾部数据是 Kindle 场景的经典坑。
"""
from __future__ import annotations

import hashlib
import os
import shutil

CHUNK = 1024 * 1024

# 结构复检里不算硬伤的问题：DRM 只影响「谁能读」，不影响「文件是不是完好的」
_SOFT_MARKS = ("DRM", "加密")

# 指纹缓存：key=(规范化路径, 大小, mtime_ns)。命中就别再读一遍整本书了。
_HASH_CACHE: dict[tuple, str] = {}
_CACHE_MAX = 512


class IntegrityError(Exception):
    """复制或校验失败。消息直接给用户看，所以要写成人话。"""


def _cache_key(path: str, size: int, mtime_ns: int) -> tuple:
    return (os.path.normcase(os.path.abspath(path)), size, mtime_ns)


def stat_of(path: str) -> tuple[int, int]:
    """(大小, mtime_ns)。取不到就返回 (-1, -1)，不抛异常。"""
    try:
        st = os.stat(path)
        return st.st_size, st.st_mtime_ns
    except OSError:
        return -1, -1


def sha256_of(path: str) -> str:
    """全量 sha256，结果按 (路径, 大小, mtime) 缓存。"""
    size, mtime = stat_of(path)
    if size < 0:
        return ""
    key = _cache_key(path, size, mtime)
    hit = _HASH_CACHE.get(key)
    if hit:
        return hit
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                blob = f.read(CHUNK)
                if not blob:
                    break
                h.update(blob)
    except OSError as ex:
        raise IntegrityError(f"读取失败：{ex}") from ex
    if len(_HASH_CACHE) >= _CACHE_MAX:
        _HASH_CACHE.clear()
    _HASH_CACHE[key] = h.hexdigest()
    return _HASH_CACHE[key]


def fingerprint(path: str) -> tuple[int, str]:
    """(大小, sha256)。大小不同就足以判定不同，sha 只在需要时算。"""
    size, _ = stat_of(path)
    return size, sha256_of(path) if size >= 0 else ""


def same_content(a: str, b: str) -> bool:
    """两份文件内容是否完全一致。先比大小，省掉绝大多数哈希开销。"""
    sa, _ = stat_of(a)
    sb, _ = stat_of(b)
    if sa < 0 or sb < 0 or sa != sb:
        return False
    try:
        return sha256_of(a) == sha256_of(b)
    except IntegrityError:
        return False


def free_bytes(path: str) -> int:
    """目标目录所在卷的可用字节数；取不到返回 -1（调用方按「不限制」处理）。"""
    try:
        return shutil.disk_usage(os.path.dirname(os.path.abspath(path)) or ".").free
    except OSError:
        return -1


def ensure_space(dest_dir: str, needed: int, reserve_mb: int = 32) -> str:
    """投递前先问一句：放得下吗？返回空串表示没问题。"""
    free = free_bytes(os.path.join(dest_dir, ".probe"))
    if free < 0:
        return ""
    want = needed + reserve_mb * 1048576
    if free <= want:
        return (f"设备空间不足：需要 {(needed + reserve_mb * 1048576) / 1048576:.0f} MB"
                f"（含 {reserve_mb} MB 余量），当前只剩 {free / 1048576:.0f} MB")
    return ""


def _sync_copy(src: str, tmp: str) -> None:
    """把 src 写进 tmp，写完强制落盘。"""
    with open(src, "rb") as f, open(tmp, "wb") as o:
        shutil.copyfileobj(f, o, CHUNK)
        o.flush()
        os.fsync(o.fileno())
    try:
        shutil.copystat(src, tmp)
    except OSError:
        pass                      # 时间戳抄不过去不影响内容，无所谓


def copy_verified(src: str, dst: str) -> int:
    """复制并当场验货：大小 + sha256 双重比对。

    流程是「临时文件 → fsync → 校验 → 原子改名」：
      · 中途断电/拔线，设备上只会多一个 .kbtmp 临时文件，不会多一本坏书；
      · 校验不过，临时文件直接删掉，不留下残缺品；
      · os.replace 是原子操作，不会出现「改到一半」的目录项。
    成功返回目标文件大小。
    """
    tmp = dst + ".kbtmp"
    try:
        _sync_copy(src, tmp)
    except OSError as ex:
        _quiet_remove(tmp)
        raise IntegrityError(f"写入失败：{ex}") from ex

    try:
        sa = os.path.getsize(src)
        sb = os.path.getsize(tmp)
        if sa != sb:
            raise IntegrityError(f"复制后大小不一致（源 {sa} → 目标 {sb} 字节）")
        if sha256_of(src) != sha256_of(tmp):
            raise IntegrityError("复制后内容校验不一致，文件可能在写入中被截断")
    except IntegrityError:
        _quiet_remove(tmp)
        raise

    try:
        os.replace(tmp, dst)
    except OSError as ex:
        _quiet_remove(tmp)
        raise IntegrityError(f"替换目标文件失败：{ex}") from ex
    return os.path.getsize(dst)


def _quiet_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def check_openable(path: str) -> tuple[bool, str]:
    """拷完之后再问一句：这东西 Kindle 打得开吗？

    复用现成的体检器，不自己造轮子。返回 (能不能用, 说明)。
    只报硬伤（issues），warnings 不算拦路问题。
    """
    from . import epub as epub_mod
    from . import mobi as mobi_mod

    if not os.path.isfile(path):
        return False, "目标文件不存在"
    if os.path.getsize(path) <= 0:
        return False, "目标文件是空的"

    try:
        kind = mobi_mod.sniff(path)
        if kind in ("mobi", "kfx"):
            rep = mobi_mod.inspect_mobi(path)
        elif kind == "epub":
            rep = epub_mod.inspect_epub(path)
        else:
            # PDF / TXT 之类：没有体检器，文件头对得上就算过
            return True, "非 MOBI/EPUB，跳过结构复检"
    except Exception as ex:                     # 体检器本身也不能把投递流程搞崩
        return False, f"结构复检异常：{type(ex).__name__}: {ex}"

    # DRM 是「能不能读」的问题，不是「文件坏没坏」的问题。
    # 个人买的加密书拷贝到本设备上是合法的，不能因为加密就判定文件损坏。
    hard = [i for i in rep.get("issues", [])
            if not any(m in i.get("msg", "") for m in _SOFT_MARKS)]
    if hard:
        return False, f"结构复检未通过：{hard[0].get('msg', '结构异常')}"
    return True, f"{rep.get('format') or '文件'} 结构正常"


def size_text(n: int) -> str:
    """给人类看的体积。"""
    if n >= 1048576:
        return f"{n / 1048576:.1f} MB"
    if n >= 1024:
        return f"{n // 1024} KB"
    return f"{n} 字节"
