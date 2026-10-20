"""把 chinese-poetry（MIT）的正文数据拉到本地语料目录。

只下正文 JSON，跳过 strains / rank（宋诗的格律标注与词频排名，是同一批数据的衍生品）、
images、以及 ci.db（SQLite 快照，正文在 JSON 里已经有了）。

支持断点：已存在且字节数一致的文件直接跳过，所以中断后再跑一次是安全的。

用法：
    python _tools/fetch-chinese-poetry.py            # 下载
    python _tools/fetch-chinese-poetry.py --check    # 只校验不下载
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# 正文所在的目录。strains / rank 是衍生数据，体积占一半以上，不拉。
KEEP_DIRS = (
    "全唐诗",        # 唐诗 5.5 万首 + 宋诗 26 万首（含作者表）
    "御定全唐詩",    # 全唐诗的御定刻本，分卷 JSON
    "宋词",          # 两宋 1564 位词人 21050 首
    "元曲",
    "五代诗词",      # 花间集
    "四书五经",      # 大学、中庸、孟子
    "论语", "诗经", "楚辞",
    "蒙学",          # 三字经、百家姓、千字文等
    "纳兰性德", "曹操诗集",
    "幽梦影", "水墨唐诗",
)

TREE_URL = "https://api.github.com/repos/chinese-poetry/chinese-poetry/git/trees/master?recursive=1"
RAW = "https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/"
UA = "KindleBridge/1.3 (local personal tool; MIT corpus)"
WORKERS = 8
TRIES = 3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(BASE, "corpus", "chinese-poetry")

_lock = threading.Lock()
_done = 0
_bytes = 0
_failed: list[str] = []


def fetch_tree() -> list[dict]:
    req = urllib.request.Request(TREE_URL, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    if "tree" not in data:
        raise SystemExit("拿不到文件树：" + str(data)[:200])
    return data["tree"]


def wanted(tree: list[dict]) -> list[dict]:
    out = []
    for t in tree:
        if t.get("type") != "blob":
            continue
        path = t["path"]
        if not path.endswith(".json"):
            continue
        top = path.split("/", 1)[0]
        if top not in KEEP_DIRS:
            continue
        out.append({"path": path, "size": t.get("size") or 0})
    return out


def _get(url: str, timeout: float = 60.0) -> bytes:
    last: Exception | None = None
    for _ in range(TRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as ex:          # noqa: BLE001 - 网络类错误一律重试
            last = ex
            time.sleep(0.6)
    raise RuntimeError(str(last))


def one(item: dict, check_only: bool) -> tuple[str, int, str]:
    """返回 (状态, 字节数, 说明)。状态：ok / skip / fail"""
    rel = item["path"]
    dst = os.path.join(CORPUS, rel)
    want = item["size"]

    if os.path.isfile(dst) and (not want or os.path.getsize(dst) == want):
        return "skip", want or os.path.getsize(dst), rel

    if check_only:
        return "fail", 0, rel + "（缺失）"

    url = RAW + urllib.parse.quote(rel)
    try:
        blob = _get(url)
    except Exception as ex:              # noqa: BLE001
        with _lock:
            _failed.append(rel)
        return "fail", 0, f"{rel} :: {ex}"

    if want and len(blob) != want:
        # 大小对不上说明下载不完整，写 .part 由下一轮重下，绝不留下坏数据
        with _lock:
            _failed.append(rel)
        return "fail", 0, f"{rel} 大小不符 {len(blob)} != {want}"

    tmp = dst + ".part"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, dst)                 # 原子落盘，不留半截文件
    return "ok", len(blob), rel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验本地副本，不下载")
    ap.add_argument("--only", nargs="*", default=None,
                    help="只下这些目录（用于先把精华小书下完，大部头后台续传）")
    ap.add_argument("--small-first", action="store_true",
                    help="小文件优先，先用起来再补齐")
    args = ap.parse_args()

    tree = fetch_tree()
    items = wanted(tree)
    if args.only:
        keep = set(args.only)
        items = [i for i in items if i["path"].split("/", 1)[0] in keep]
    if args.small_first:
        items.sort(key=lambda i: i["size"])
    total_mb = sum(i["size"] for i in items) / 1048576
    print(f"待处理 {len(items)} 个 JSON，合计 {total_mb:.1f} MB")
    print(f"落盘目录 {CORPUS}")
    if args.check:
        print("（校验模式）")

    t0 = time.time()
    n_ok = n_skip = n_fail = 0
    got = 0
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(one, it, args.check): it for it in items}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            st, n, msg = fut.result()
            if st == "ok":
                n_ok += 1
                got += n
            elif st == "skip":
                n_skip += 1
            else:
                n_fail += 1
                if n_fail <= 8:
                    print("  失败:", msg, flush=True)
            if i % 100 == 0 or i == len(items):
                el = time.time() - t0
                speed = got / 1048576 / el if el else 0
                print(f"  {i}/{len(items)}  新增 {n_ok} 已有 {n_skip} 失败 {n_fail}"
                      f"  {got/1048576:.1f} MB  {speed:.1f} MB/s", flush=True)

    print()
    print(f"完成：新增 {n_ok}，已有 {n_skip}，失败 {n_fail}，用时 {time.time()-t0:.0f}s")
    if _failed:
        print("失败清单（前 20）：")
        for p in _failed[:20]:
            print("   ", p)
        print("再跑一次本脚本即可续传。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
