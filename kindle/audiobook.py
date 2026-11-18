# -*- coding: utf-8 -*-
"""整本书导出有声书 —— ebook2audiobook（E2A）检测与调用。

这个模块刻意只做三件事：

1. **如实检测**：多路径探测 ``ebook2audiobook`` 命令，读出真实版本号；
2. **给安装指引**：E2A 是 pip 包、没有 exe 安装包可取，所以只给一键可复制的
   官方安装命令，不静默安装、不下载任何东西、不碰系统设置；
3. **headless 调用**：把书架里的书转成带章节的 m4b，落到 ``export/``，
   带进度与取消。

为什么是外部工具而不是内置依赖：
  - E2A 带 50+ TTS 引擎、每个引擎独立 venv + PyTorch，体量远超本工具的
    「核心零重依赖」定位；做成本地 TTS 那样可选依赖也会拖慢启动。
  - 它的许可证是 Apache-2.0，与本项目 MIT 兼容；纯子进程调用不复制它的
    代码进仓库，连分发署名义务都不触发（见 THIRD_PARTY_NOTICES.md）。
  - 与 Calibre 的集成方式保持一致：检测 → 引导 → 用的时候才调用。

安全边界：
  - **书路径只从 reader.resolve_path(key) 来**，绝不接收前端传来的任意路径；
  - 输出目录固定在 ``export/``，不允许调用方指定；
  - 子进程用参数列表调用，绝不用 shell=True；
  - 所有写操作加同源校验（在 app.py 层）。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from . import paths as _paths

BASE_DIR = _paths.data_dir()
OUT_DIR = os.path.join(BASE_DIR, "export")

CMD = "ebook2audiobook"

# 常见安装位置（用于向前端解释「我找过哪里」；真正判断靠 shutil.which）
def search_paths() -> list[str]:
    paths: list[str] = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        appdata = os.environ.get("APPDATA")
        home = os.path.expanduser("~")
        if local:
            paths.append(os.path.join(local, "pipx", "venvs", "ebook2audiobook",
                                      "Scripts", CMD + ".exe"))
        paths.append(os.path.join(home, ".local", "bin", CMD + ".exe"))
        if appdata:
            paths.append(os.path.join(appdata, "Python", "Scripts", CMD + ".exe"))
    else:
        home = os.path.expanduser("~")
        paths += [
            os.path.join(home, ".local", "bin", CMD),
            "/usr/local/bin/" + CMD,
            "/usr/bin/" + CMD,
            os.path.join(home, ".pipx", "venvs", "ebook2audiobook", "bin", CMD),
        ]
    return paths


def exe_path() -> str:
    found = shutil.which(CMD)
    if found:
        return found
    for p in search_paths():
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return ""


_VER_LOCK = threading.Lock()
_VER_CACHE: dict = {"key": "", "at": 0.0, "version": ""}
_VER_TTL = 300.0
_VER_RE = re.compile(r"(\d+\.\d+(?:\.\d+)*)")


def version_of(exe: str, ttl: float = _VER_TTL) -> str:
    """读版本号。E2A 启动要加载依赖，带 5 分钟缓存。"""
    if not exe:
        return ""
    with _VER_LOCK:
        if _VER_CACHE["key"] == exe and time.time() - _VER_CACHE["at"] < ttl:
            return _VER_CACHE["version"]
    ver = ""
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        m = _VER_RE.search(f"{proc.stdout or ''}\n{proc.stderr or ''}")
        if m:
            ver = m.group(1)
    except (OSError, subprocess.SubprocessError):
        ver = ""
    with _VER_LOCK:
        _VER_CACHE.update({"key": exe, "at": time.time(), "version": ver})
    return ver


def detect(force: bool = False) -> dict:
    exe = exe_path()
    if force:
        with _VER_LOCK:
            _VER_CACHE.update({"key": "", "at": 0.0, "version": ""})
    ver = version_of(exe) if exe else ""
    return {
        "ok": bool(exe),
        "path": exe,
        "version": ver,
        "searched": search_paths(),
    }


# ---------------------------------------------------------------- 安装指引
def install_hint() -> dict:
    """E2A 没有 exe 安装包，只给官方安装命令，不代跑、不代下。"""
    if os.name == "nt":
        cmds = ["pipx install ebook2audiobook",
                "uv tool install ebook2audiobook"]
        note = "装完重开命令行，回到本页点「重新检测」。Windows 路径不要太长（建议 ≤ 179 字符）。"
    else:
        cmds = ["pipx install ebook2audiobook",
                "uv tool install ebook2audiobook"]
        note = "装完回到本页点「重新检测」。若 pipx 未安装，先按系统包管理器装 pipx。"
    return {
        "commands": cmds,
        "official": "https://github.com/DrewThomasson/ebook2audiobook",
        "note": note,
    }


# ---------------------------------------------------------------- 语言映射
# 本项目用 zh/en 简写，E2A 用 ISO-639-3（zho/eng），这里做宽松兜底。
_LANG_MAP = {
    "zh": "zho", "cn": "zho", "zh-cn": "zho", "zho": "zho",
    "en": "eng", "eng": "eng",
}
_DEFAULT_LANG = "zho"


def e2a_lang(lang: str) -> str:
    key = (lang or "").strip().lower()
    return _LANG_MAP.get(key, key or _DEFAULT_LANG)


# ---------------------------------------------------------------- 转换进度
_PROG_LOCK = threading.Lock()
_PROG: dict = {
    "active": False, "phase": "idle", "book": "", "output": "",
    "error": "", "log": [], "started": 0.0, "finished": 0.0,
}
_PROC: dict = {"proc": None}
_PROC_LOCK = threading.Lock()
_STOP = threading.Event()

# 输出音频后缀（E2A 支持的都列上，用于识别新产物）
_AUDIO_EXTS = (".m4b", ".m4a", ".mp3", ".flac", ".wav", ".ogg", ".aac", ".mp4", ".webm")


def _set_prog(**kw) -> None:
    with _PROG_LOCK:
        _PROG.update(kw)


def progress() -> dict:
    with _PROG_LOCK:
        return dict(_PROG)


def _snapshot_outputs() -> set[str]:
    try:
        return {
            os.path.join(OUT_DIR, n) for n in os.listdir(OUT_DIR)
            if n.lower().endswith(_AUDIO_EXTS)
        }
    except OSError:
        return set()


def _new_outputs(before: set[str]) -> list[str]:
    after = _snapshot_outputs()
    fresh = [p for p in after - before if os.path.isfile(p) and os.path.getsize(p) > 0]
    fresh.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return fresh


def _convert_worker(exe: str, book_path: str, lang: str, engine: str,
                    before: set[str], shown: str) -> None:
    started = time.time()
    _STOP.clear()
    log: list[str] = []
    os.makedirs(OUT_DIR, exist_ok=True)
    cmd = [exe, "--headless", "--ebook", book_path,
           "--language", e2a_lang(lang), "--output_format", "m4b",
           "--output_dir", OUT_DIR]
    if engine:
        cmd += ["--tts_engine", engine]
    _set_prog(active=True, phase="converting", book=shown, output="", error="",
              log=[], started=started, finished=0.0)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        with _PROC_LOCK:
            _PROC["proc"] = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            if _STOP.is_set():
                proc.terminate()
                break
            line = line.rstrip()
            if not line:
                continue
            log.append(line[-400:])
            if len(log) > 40:
                log.pop(0)
            # E2A 的 headless 输出格式会随版本变，不强解析百分比，
            # 只把最近几行原样给前端看，诚实反映进度。
            _set_prog(log=log[-12:])
        rc = proc.wait(timeout=30)
        with _PROC_LOCK:
            _PROC["proc"] = None
        if _STOP.is_set():
            raise InterruptedError()
        if rc != 0:
            raise RuntimeError(f"E2A 退出码 {rc}（详见日志）")
        fresh = _new_outputs(before)
        if not fresh:
            raise RuntimeError("转换结束但没在 export/ 找到音频文件，请查看日志")
        _set_prog(active=False, phase="done", output=fresh[0],
                  finished=time.time(), error="", log=log[-12:])
    except InterruptedError:
        _set_prog(active=False, phase="cancelled", finished=time.time(),
                  error="已取消", log=log[-12:])
    except (OSError, subprocess.SubprocessError, RuntimeError) as ex:
        _set_prog(active=False, phase="error", finished=time.time(),
                  error=f"{type(ex).__name__}: {ex}"[:400], log=log[-12:])
    finally:
        with _PROC_LOCK:
            _PROC["proc"] = None


def start_convert(book_path: str, lang: str = "zh", engine: str = "",
                  shown: str = "") -> dict:
    """启动整本转换。book_path 必须是调用方已用 reader.resolve_path 校验过的路径。"""
    if progress()["active"]:
        return {"ok": False, "error": "已有一个转换任务在进行中"}
    exe = exe_path()
    if not exe:
        return {"ok": False, "error": "未检测到 ebook2audiobook，请先按下方命令安装"}
    if not book_path or not os.path.isfile(book_path):
        return {"ok": False, "error": "书籍文件不存在"}
    real = os.path.realpath(book_path)
    root = os.path.realpath(BASE_DIR)
    try:
        if os.path.commonpath([real, root]) != root:
            return {"ok": False, "error": "拒绝转换工作目录之外的文件"}
    except ValueError:
        return {"ok": False, "error": "路径不合法"}
    before = _snapshot_outputs()
    shown = shown or os.path.basename(book_path)
    threading.Thread(target=_convert_worker,
                     args=(exe, book_path, lang, engine, before, shown),
                     daemon=True).start()
    return {"ok": True, "book": shown, "output_dir": OUT_DIR, "language": e2a_lang(lang)}


def cancel_convert() -> dict:
    if not progress()["active"]:
        return {"ok": False, "error": "当前没有转换任务"}
    _STOP.set()
    with _PROC_LOCK:
        proc = _PROC["proc"]
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass
    return {"ok": True, "note": "正在停止转换，已生成的音频会保留在 export/"}


def state(force: bool = False) -> dict:
    return {
        "e2a": detect(force=force),
        "install": install_hint(),
        "progress": progress(),
        "output_dir": OUT_DIR,
    }
