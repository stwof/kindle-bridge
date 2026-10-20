# -*- coding: utf-8 -*-
"""Calibre 检测与安装引导。

路线 A（EPUB → AZW3）依赖 Calibre。这个模块只做两件事：

1. **如实检测**：多路径探测 ``ebook-convert``，读出真实版本号；
2. **把安装包替你取回来**：从官方分发入口下载到工具的 ``工具/`` 目录，
   由你双击安装。

刻意不做的事：不静默安装、不写注册表、不改 PATH、不碰系统设置。
下载来源被限定在官方白名单域名内，落盘前校验安装包魔数与 SHA-256。
"""
from __future__ import annotations

import hashlib
import ctypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from . import paths as _paths

BASE_DIR = _paths.data_dir()
TOOL_DIR = os.path.join(BASE_DIR, "工具")

# 官方分发入口：302 跳到当前版本的安装包。官方页面亦可。
ENTRY_URL = "https://calibre-ebook.com/dist/win64"
OFFICIAL_PAGE = "https://calibre-ebook.com/download_windows"
ALLOWED_HOSTS = {
    "calibre-ebook.com",
    "www.calibre-ebook.com",
    "download.calibre-ebook.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
UA = "KindleBridge/1.1 (local tool; +https://calibre-ebook.com)"

# OLE 复合文档（.msi 实为这种容器）；.exe 以 MZ 开头
MSI_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
EXE_MAGIC = b"MZ"

CHUNK = 256 * 1024
VERSION_TTL = 120.0
SHA_CACHE: dict = {}


# ---------------------------------------------------------------- 检测
def _exe_name() -> str:
    return "ebook-convert.exe" if os.name == "nt" else "ebook-convert"


def search_paths() -> list[str]:
    """会被检查的候选位置（用于向前端解释「我找过哪里」）。"""
    exe = _exe_name()
    paths: list[str] = []
    if os.name == "nt":
        bases = [
            os.environ.get("ProgramFiles") or r"C:\Program Files",
            os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)",
        ]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            bases.append(os.path.join(local, "Programs"))
        for base in bases:
            paths.append(os.path.join(base, "Calibre2", exe))
            paths.append(os.path.join(base, "calibre", exe))
    else:
        paths += [
            "/usr/bin/ebook-convert",
            "/usr/local/bin/ebook-convert",
            "/Applications/calibre.app/Contents/MacOS/ebook-convert",
        ]
    return paths


def ebook_convert_path() -> str:
    """当前可用的 ebook-convert 路径（复用 convert 模块的探测逻辑）。"""
    from .convert import find_ebook_convert

    return find_ebook_convert() or ""


_VER_LOCK = threading.Lock()
_VER_CACHE: dict = {"key": "", "at": 0.0, "version": ""}

_VER_RE = re.compile(r"(\d+\.\d+(?:\.\d+)*)")


def version_of(exe: str, ttl: float = VERSION_TTL) -> str:
    """读取 Calibre 版本号。Calibre 启动较慢，所以带缓存。"""
    if not exe:
        return ""
    with _VER_LOCK:
        if _VER_CACHE["key"] == exe and time.time() - _VER_CACHE["at"] < ttl:
            return _VER_CACHE["version"]
    ver = ""
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True, text=True, timeout=40,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        m = _VER_RE.search(text)
        if m:
            ver = m.group(1)
    except (OSError, subprocess.SubprocessError):
        ver = ""
    with _VER_LOCK:
        _VER_CACHE.update({"key": exe, "at": time.time(), "version": ver})
    return ver


def detect(force: bool = False) -> dict:
    exe = ebook_convert_path()
    if force:
        with _VER_LOCK:
            _VER_CACHE.update({"key": "", "at": 0.0, "version": ""})
    ver = version_of(exe) if exe else ""
    return {
        "ok": bool(exe),
        "path": exe,
        "version": ver,
        "searched": search_paths(),
        "winget": bool(shutil.which("winget")),
    }


# ---------------------------------------------------------------- 安装包
def _installer_candidates() -> list[str]:
    if not os.path.isdir(TOOL_DIR):
        return []
    out = []
    for name in sorted(os.listdir(TOOL_DIR)):
        low = name.lower()
        if not low.startswith("calibre"):
            continue
        if not (low.endswith(".msi") or low.endswith(".exe")):
            continue
        full = os.path.join(TOOL_DIR, name)
        if os.path.isfile(full) and os.path.getsize(full) > 1024 * 1024:
            out.append(full)
    return out


def _find_installer() -> str:
    cands = _installer_candidates()
    if not cands:
        return ""
    return max(cands, key=os.path.getmtime)


def probe_installer(path: str) -> str:
    """按魔数判断这到底是不是一个正常的安装包。"""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return "unreadable"
    if head.startswith(MSI_MAGIC):
        return "msi"
    if head.startswith(EXE_MAGIC):
        return "exe"
    return "unknown"


def _sha256(path: str) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return ""
    key = (path, st.st_size, int(st.st_mtime))
    if SHA_CACHE.get("key") == key:
        return SHA_CACHE.get("value", "")
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
    except OSError:
        return ""
    val = h.hexdigest()
    SHA_CACHE.update({"key": key, "value": val})
    return val


def installer_info() -> dict:
    p = _find_installer()
    if not p:
        return {"ready": False, "file": "", "name": "", "size": 0,
                "modified": "", "kind": "", "sha256": ""}
    st = os.stat(p)
    kind = probe_installer(p)
    return {
        "ready": kind in ("msi", "exe"),
        "file": p,
        "name": os.path.basename(p),
        "size": st.st_size,
        "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
        "kind": kind,
        "sha256": _sha256(p),
    }


# ---------------------------------------------------------------- 下载
# 跨海线路动辄十几 KB/s，228 MB 单连接要几小时，中途断了还得从头来。
# 所以这里做三件事：分片并发、按 Range 断点续传、随时可取消。
SEGMENTS = 4

_PROG_LOCK = threading.Lock()
_PROG: dict = {
    "active": False, "phase": "idle", "downloaded": 0, "total": 0,
    "file": "", "url": "", "error": "", "started": 0.0, "finished": 0.0,
    "speed": 0.0, "eta": 0, "segments": 0, "resumed": 0, "sha256": "",
}

_SEG_LOCK = threading.Lock()
_SEG_BYTES: dict[int, int] = {}
_STOP = threading.Event()


def _set_prog(**kw) -> None:
    with _PROG_LOCK:
        _PROG.update(kw)


def progress() -> dict:
    with _PROG_LOCK:
        return dict(_PROG)


def _check_url(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"拒绝非官方来源：{host or '（无主机名）'}")


def _open_url(url: str, method: str = "GET", timeout: float = 30.0):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def resolve_latest(timeout: float = 30.0) -> tuple[str, str, int]:
    """跟随官方分发入口的重定向，得到 (最终 URL, 文件名, 字节数)。"""
    with _open_url(ENTRY_URL, method="HEAD", timeout=timeout) as resp:
        final = resp.geturl()
        size = int(resp.headers.get("Content-Length") or 0)
    _check_url(final)
    name = os.path.basename(urlparse(final).path) or "calibre-installer.msi"
    return final, name, size


def _supports_range(url: str, timeout: float = 25.0) -> bool:
    """探测服务器是否接受 Range。接受才能续传和分片。"""
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 206 and "content-range" in {
                k.lower() for k in resp.headers.keys()}
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _seg_path(final: str, i: int) -> str:
    return f"{final}.part{i}"


def _fetch_segment(url: str, final: str, i: int, start: int, end: int) -> None:
    """下载 [start, end]；若已有 .partN 则从断点接着写。"""
    path = _seg_path(final, i)
    span = end - start + 1
    have = os.path.getsize(path) if os.path.isfile(path) else 0
    if have > span:                 # 分片文件异常（多半是换了版本），重来
        os.remove(path)
        have = 0
    with _SEG_LOCK:
        _SEG_BYTES[i] = have
    if have >= span:
        return

    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Range": f"bytes={start + have}-{end}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status == 200:
            # 服务器忽略了 Range：只有从头整段拉才安全
            if start or have:
                raise ValueError("服务器不支持断点续传")
        elif resp.status != 206:
            raise ValueError("服务器返回了意外的状态（HTTP %s）" % resp.status)
        with open(path, "ab") as f:
            written = have
            with _SEG_LOCK:
                _SEG_BYTES[i] = written
            while not _STOP.is_set():
                block = resp.read(CHUNK)
                if not block:
                    break
                f.write(block)
                written += len(block)
                with _SEG_LOCK:
                    _SEG_BYTES[i] = written
            f.flush()
            if _STOP.is_set():
                raise InterruptedError("已取消")
    if written < span:
        raise ValueError(f"分片 {i} 未下完（{written}/{span}）")


def _merge_segments(final: str, n: int) -> str:
    """把 n 个分片按序拼成完整文件；分片先留着，校验通过后再删。"""
    out = final + ".part"
    try:
        with open(out, "wb") as dst:
            for i in range(n):
                with open(_seg_path(final, i), "rb") as seg:
                    shutil.copyfileobj(seg, dst, 1024 * 1024)
    except OSError:
        try:
            os.remove(out)
        except OSError:
            pass
        raise
    return out


def _drop_segments(final: str, n: int) -> None:
    for i in range(n):
        try:
            os.remove(_seg_path(final, i))
        except OSError:
            pass


def _plan(total: int, n: int) -> list[tuple[int, int]]:
    """把 total 字节切成 n 段。"""
    size = total // n
    return [(i * size, (total - 1) if i == n - 1 else (i + 1) * size - 1)
            for i in range(n)]


def _overall() -> int:
    with _SEG_LOCK:
        return sum(_SEG_BYTES.values())


def _is_complete(path: str, total: int) -> bool:
    if not os.path.isfile(path):
        return False
    if total and os.path.getsize(path) != total:
        return False
    return probe_installer(path) in ("msi", "exe")


def partial_info() -> dict:
    """续传残留：上次下了多少、留下了几个分片文件。"""
    if not os.path.isdir(TOOL_DIR):
        return {"bytes": 0, "files": 0}
    total = files = 0
    for n in os.listdir(TOOL_DIR):
        low = n.lower()
        if low.startswith("calibre") and ".part" in low:
            p = os.path.join(TOOL_DIR, n)
            if os.path.isfile(p):
                total += os.path.getsize(p)
                files += 1
    return {"bytes": total, "files": files}


def _download_worker(force: bool) -> None:
    started = time.time()
    _STOP.clear()
    with _SEG_LOCK:
        _SEG_BYTES.clear()
    try:
        _set_prog(active=True, phase="resolving", error="", downloaded=0, total=0,
                  url="", file="", started=started, finished=0.0, speed=0.0,
                  eta=0, segments=0, resumed=0, sha256="")
        url, name, total = resolve_latest()
        name = re.sub(r"[^A-Za-z0-9._+-]", "_", name) or "calibre-installer.msi"
        os.makedirs(TOOL_DIR, exist_ok=True)
        final = os.path.join(TOOL_DIR, name)

        if force:
            for p in [final] + [_seg_path(final, i) for i in range(SEGMENTS)]:
                if os.path.exists(p):
                    os.remove(p)
        elif _is_complete(final, total):
            info = installer_info()
            _set_prog(active=False, phase="done", finished=time.time(),
                      downloaded=total, total=total, file=name,
                      sha256=info.get("sha256", ""))
            return

        if not total:
            raise ValueError("未能取到安装包体积信息，请稍后重试")

        use_seg = _supports_range(url)
        n = SEGMENTS if use_seg else 1
        plan = _plan(total, n)
        resumed = sum(os.path.getsize(_seg_path(final, i))
                      for i in range(n) if os.path.isfile(_seg_path(final, i)))
        _set_prog(phase="downloading", url=url, file=name, total=total,
                  segments=n, resumed=resumed, downloaded=resumed)

        if n == 1:
            _fetch_segment(url, final, 0, 0, total - 1)
        elif n > 1:
            errs: list[BaseException] = []

            def run(i, s, e):
                try:
                    _fetch_segment(url, final, i, s, e)
                except BaseException as ex:      # noqa: BLE001 交由主线程统一处理
                    errs.append(ex)

            threads = [threading.Thread(target=run, args=(i, s, e), daemon=True)
                       for i, (s, e) in enumerate(plan)]
            for t in threads:
                t.start()

            last_t, last_v = time.time(), _overall()
            while any(t.is_alive() for t in threads):
                time.sleep(0.4)
                now = time.time()
                done = _overall()
                if now - last_t >= 2.0:
                    win = max(done - last_v, 0) / (now - last_t)
                    # 低速链路上单窗口常取到 0，用开工以来的均值兜底，保证 ETA 有意义
                    avg = max(done - resumed, 0) / max(now - started, 1.0)
                    spd = win if win > 512 else max(avg, win)
                    _set_prog(downloaded=done, speed=spd,
                              eta=int((total - done) / spd) if spd > 512 else 0)
                    last_t, last_v = now, done
                else:
                    # 速度/ETA 每 2 秒算一次就够，但字节数每一拍都要刷，
                    # 否则页面上的进度条会出现「两秒不动、然后跳一格」的观感
                    _set_prog(downloaded=done)
            for t in threads:
                t.join()
            _set_prog(downloaded=_overall())
            if _STOP.is_set():
                raise InterruptedError("已取消")
            if errs:
                raise errs[0]

        _set_prog(phase="merging")
        part = _merge_segments(final, n)
        got = os.path.getsize(part)
        if got != total:
            raise ValueError(f"下载不完整：{got} / {total} 字节")
        if probe_installer(part) not in ("msi", "exe"):
            raise ValueError("文件头不是有效的 Windows 安装包，已丢弃")
        os.replace(part, final)
        _drop_segments(final, n)

        info = installer_info()
        _set_prog(active=False, phase="done", finished=time.time(),
                  downloaded=got, total=total, file=name,
                  sha256=info.get("sha256", ""), eta=0,
                  speed=got / max(time.time() - started, 0.001))
    except InterruptedError:
        _set_prog(active=False, phase="cancelled", finished=time.time(),
                  error="已取消（已下部分保留，下次可继续）", eta=0)
    except (urllib.error.URLError, OSError, ValueError) as ex:
        _set_prog(active=False, phase="error", finished=time.time(),
                  error=f"{type(ex).__name__}: {ex}"[:300], eta=0)


def cancel_download() -> dict:
    if not progress()["active"]:
        return {"ok": False, "error": "当前没有下载任务"}
    _STOP.set()
    return {"ok": True, "note": "正在停止，已下载的部分会保留，下次点「继续下载」即可续传"}


def start_download(force: bool = False) -> dict:
    if progress()["active"]:
        return {"ok": False, "error": "已有下载任务在进行中"}
    if not force and installer_info()["ready"]:
        return {"ok": False, "error": "安装包已经在「工具」目录里了，无需重复下载"}
    threading.Thread(target=_download_worker, args=(force,), daemon=True).start()
    return {"ok": True, "tool_dir": TOOL_DIR, "partial": partial_info()}


# ---------------------------------------------------------------- 打开 / 运行
def reveal_installer() -> dict:
    """在资源管理器里定位到安装包（没下载则打开「工具」目录）。"""
    p = _find_installer()
    os.makedirs(TOOL_DIR, exist_ok=True)
    try:
        if os.name == "nt":
            if p:
                # explorer 的 /select 必须与路径连写，否则会被当成两个参数
                subprocess.Popen(["explorer", "/select," + os.path.normpath(p)])
            else:
                os.startfile(TOOL_DIR)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", p] if p else ["open", TOOL_DIR])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(p) if p else TOOL_DIR])
    except OSError as ex:
        return {"ok": False, "error": f"打开失败：{ex}"}
    return {"ok": True, "revealed": bool(p), "file": p, "dir": TOOL_DIR}


def run_installer() -> dict:
    """启动官方安装向导。只允许运行我们自己下载并校验过的那个文件。"""
    p = _find_installer()
    if not p:
        return {"ok": False, "error": "「工具」目录里还没有安装包，请先下载"}
    kind = probe_installer(p)
    if kind not in ("msi", "exe"):
        return {"ok": False, "error": "魔数校验未通过，这不是一个有效的安装包，已拒绝运行"}
    if os.path.basename(p).startswith("~"):
        return {"ok": False, "error": "这是一个临时文件，已拒绝运行"}
    try:
        if os.name == "nt":
            # MSI 写系统目录要管理员权限。普通权限启动会装到一半报 2503，
            # 所以用 runas 动词触发 UAC 提权，而不是 os.startfile 的 open 动词。
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", p, None, None, 1)  # type: ignore[attr-defined]
            if rc <= 32:
                return {"ok": False, "error": "未获得管理员授权（UAC 被取消或被系统策略拦下）"}
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except OSError as ex:
        return {"ok": False, "error": f"启动失败：{ex}"}
    return {
        "ok": True, "file": p, "name": os.path.basename(p),
        "note": "安装向导已打开。默认装到 C:\\Program Files\\Calibre2，装完回到本页点「重新检测」。",
    }


# ---------------------------------------------------------------- 汇总
def state(force: bool = False) -> dict:
    inst = installer_info()
    return {
        "calibre": detect(force=force),
        "installer": inst,
        "partial": partial_info(),
        "progress": progress(),
        "tool_dir": TOOL_DIR,
        "entry_url": ENTRY_URL,
        "official_page": OFFICIAL_PAGE,
    }
