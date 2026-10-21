# -*- coding: utf-8 -*-
"""字典查询测试：内置离线词表 + /api/dict/lookup 接口。

离线优先、纯内存查找，不联网；若仓库根目录「字典/」下有 CC-CEDICT StarDict
则一并加载（本测试环境通常没有，所以主要验离线词表 + 接口接线）。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from kindle import dictdata as D                                     # noqa: E402

ok = fail = 0


def chk(cond, msg):
    global ok, fail
    if cond:
        ok += 1
        print("  [OK]  ", msg)
    else:
        fail += 1
        print("  [FAIL]", msg)


def section(t):
    print(f"\n--- {t} ---")


def free_port(preferred):
    for p in (preferred, preferred + 1, preferred + 2, preferred + 3):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("找不到可用端口")


# ---------------------------------------------------------------------------
# 一、离线词表 / 查找逻辑
# ---------------------------------------------------------------------------
section("离线词表与查找逻辑")

r = D.lookup("你好")
chk(r["found"] and r["word"] == "你好" and "hello" in r["entries"][-1], "中文整词命中：你好")

r = D.lookup("world")
chk(r["found"], "英文命中：world")

r = D.lookup("World")
chk(r["found"], "英文大小写不敏感：World → world")

r = D.lookup("你好。")
chk(r["found"] and r["word"] == "你好", "去掉首尾标点：『你好。』→ 你好")

r = D.lookup("  the  ")
chk(r["found"] and r["word"] == "the", "去首尾空白：the")

r = D.lookup("zzzznotaword")
chk(not r["found"] and r["entries"] == [], "未收录词返回 found=false 且 entries 为空")

# 缓存机制：连续两次 lookup 不报错、结果一致
r1 = D.lookup("朋友")
r2 = D.lookup("朋友")
chk(r1["found"] and r1["entries"] == r2["entries"], "重复查询一致（走缓存）")

# 词条数量合理（离线词表至少几百条）
n = len(D._load_quick())
chk(n >= 200, f"离线词表规模 >= 200 条（实际 {n} 条）")

# ---------------------------------------------------------------------------
# 二、/api/dict/lookup 接口（起一个真实服务打一遍）
# ---------------------------------------------------------------------------
section("/api/dict/lookup 接口")
port = free_port(8793)
env = dict(os.environ)
env["NO_PROXY"] = "127.0.0.1,localhost"
env["no_proxy"] = "127.0.0.1,localhost"
srv = subprocess.Popen(
    [sys.executable, os.path.join(ROOT, "app.py"), "--port", str(port), "--no-browser"],
    cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    up = False
    for _ in range(60):
        time.sleep(0.4)
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                up = True
                break
    chk(up, f"服务在 {port} 起得来")

    def get(q):
        url = f"http://127.0.0.1:{port}/api/dict/lookup?q=" + urllib.request.quote(q)
        with urllib.request.urlopen(url, timeout=10) as r:
            import json
            return json.loads(r.read().decode("utf-8"))

    res = get("你好")
    chk(res.get("found") and res.get("word") == "你好", "接口命中中文：你好")

    res = get("nonexistentxyz")
    chk(res.get("found") is False, "接口未命中返回 found=false")

    # 端点不存在的兜底：故意打一个错词也应是 200 + JSON（不是 500）
    res = get("")
    chk(isinstance(res, dict), "空查询也返回 JSON（不崩）")
finally:
    srv.terminate()
    try:
        srv.wait(timeout=5)
    except Exception:
        srv.kill()


print(f"\n字典测试：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
