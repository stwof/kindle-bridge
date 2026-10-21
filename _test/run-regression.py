# -*- coding: utf-8 -*-
"""一条命令跑完整回归：Python 单测 + 小程序 + 前端 DOM 桩 + 真实浏览器端到端。

为什么要这个脚本：此前每加一个功能就要手动敲一长串命令，容易漏、也不��判断
到底哪一项真的挂了。现在统一在这里跑，末了给一张汇总表。

用法：
    python _test/run-regression.py              # 全跑
    python _test/run-regression.py --quick      # 跳过浏览器端到端（快很多）
    python _test/run-regression.py --only reader tts

注意：公版书库那组要连外网，在带 SSL 中间人代理的环境里会以
CERTIFICATE_VERIFY_FAILED 失败 —— 那是环境问题，不是代码问题，脚本会标注出来。
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 本机跑着服务时，让 node/python 别把 127.0.0.1 也丢给代理
_LOCAL = "127.0.0.1,localhost"


def env_for_child() -> dict:
    e = dict(os.environ)
    e["NO_PROXY"] = _LOCAL
    e["no_proxy"] = _LOCAL
    return e


def free_port(preferred: int) -> int:
    for p in (preferred, preferred + 1, preferred + 2, preferred + 3):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("找不到可用端口")


class Server:
    """临时起一个 app.py，用完就关。"""

    def __init__(self, port: int):
        self.port = port
        self.p = None

    def __enter__(self):
        exe = sys.executable
        self.p = subprocess.Popen(
            [exe, os.path.join(ROOT, "app.py"), "--port", str(self.port), "--no-browser"],
            cwd=ROOT, env=env_for_child(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            time.sleep(0.4)
            with socket.socket() as s:
                s.settimeout(0.4)
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return self
        self.__exit__(None, None, None)
        raise RuntimeError(f"服务在 {self.port} 端口没起来")

    def __exit__(self, *a):
        if self.p:
            try:
                self.p.terminate()
                self.p.wait(timeout=8)
            except Exception:                                  # noqa: BLE001
                try:
                    self.p.kill()
                except Exception:                              # noqa: BLE001
                    pass


def run(label: str, cmd: list, cwd: str = ROOT, timeout: int = 600):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env_for_child(), timeout=timeout,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        code = r.returncode
    except subprocess.TimeoutExpired:
        out, code = "（超时）", 99
    dt = time.time() - t0

    # 各套测试的收尾格式不统一，能数出总数就数，数不出的按布尔处理，
    # 但**绝不**把数不出来的当成「1 项」混进总数里冒充覆盖率。
    passed = failed = None
    for pat in (r"通过\s*(\d+)\s*项[，,]\s*失败\s*(\d+)\s*项",
                r"(\d+)\s*通过\s*/\s*(\d+)\s*失败",
                r"结果：\s*(\d+)\s*通过\s*/\s*(\d+)\s*失败"):
        m = re.search(pat, out)
        if m:
            passed, failed = int(m.group(1)), int(m.group(2))
            break
    counted = passed is not None
    if not counted:
        has_fail = any(k in out for k in ("[FAIL]", "FAIL", "✗"))
        passed, failed = (1, 0) if (code == 0 and not has_fail) else (0, 1)

    # 公版书库要联网，SSL 被代理拦掉时算「环境受限」而不是「代码坏了」
    env_blocked = "CERTIFICATE_VERIFY_FAILED" in out
    return dict(label=label, passed=passed, failed=failed, code=code, counted=counted,
                secs=dt, env_blocked=env_blocked, out=out)


def fmt(r) -> str:
    body = (f"{r['passed']:>3} 通过 / {r['failed']:>2} 失败" if r["counted"]
            else ("通过 ✓" if not r["failed"] else "失败 ✗"))
    tail = f"{r['secs']:>5.1f}s"
    if r["env_blocked"] and r["failed"]:
        tail += "  [环境受限]"
    return f"{r['label']:<20} {body}   {tail}"


PY_TESTS = [
    ("简繁内核", ["test-hanzi.py"]),
    ("简繁转换接口", ["test-zhconv.py"]),
    ("阅读器后端", ["test-reader.py"]),
    ("语音合成", ["test-tts.py"]),
    ("MOBI 体检", ["test-mobi.py"]),
    ("本地经典", ["test-classics.py"]),
    ("投递完整性", ["test-deliver-integrity.py"]),
    ("公版书库(联网)", ["test-freebooks.py"]),
]
NODE_TESTS = [
    ("微信小程序", ["test-miniprogram.js"]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过真实浏览器端到端")
    ap.add_argument("--only", nargs="*", help="只跑名字里含这些关键字的项")
    args = ap.parse_args()

    def want(label: str) -> bool:
        return not args.only or any(k in label for k in args.only)

    results = []
    py = sys.executable
    print("=" * 74)
    print("Kindle 桥 · 完整回归")
    print("=" * 74)

    print("\n【一】Python 单元测试")
    for label, argv in PY_TESTS:
        if not want(label):
            continue
        r = run(label, [py, os.path.join(HERE, argv[0])])
        results.append(r)
        print("  " + fmt(r))

    print("\n【二】Node 测试")
    for label, argv in NODE_TESTS:
        if not want(label):
            continue
        r = run(label, ["node", os.path.join(HERE, argv[0])])
        results.append(r)
        print("  " + fmt(r))

    print("\n【三】前端 DOM 桩（需要服务）")
    if want("前端DOM桩"):
        port = free_port(8791)
        with Server(port):
            r = run("前端DOM桩", ["node", os.path.join(HERE, "frontend-smoke.js")])
        results.append(r)
        print("  " + fmt(r))

    if not args.quick and want("浏览器端到端"):
        print("\n【四】真实浏览器端到端（Edge + CDP，会开无头窗口）")
        port = free_port(8795)
        with Server(port):
            r = run("浏览器端到端", ["node", os.path.join(HERE, "reader-e2e.js"), str(port)],
                    timeout=900)
        results.append(r)
        print("  " + fmt(r))

    counted = [r for r in results if r["counted"]]
    tp = sum(r["passed"] for r in counted)
    tf = sum(r["failed"] for r in results)
    bools = [r for r in results if not r["counted"]]
    print("\n" + "=" * 74)
    print(f"合计：{tp} 项断言通过 / {tf} 项失败"
          + (f"（另有 {len(bools)} 个套件整体通过）" if bools else ""))

    bad = [r for r in results if r["failed"] and not r["env_blocked"]]
    env = [r for r in results if r["failed"] and r["env_blocked"]]
    if bad:
        print("\n真正要修的：")
        for r in bad:
            print(f"  ✗ {r['label']}")
            for line in r["out"].splitlines():
                if "FAIL" in line or "✗" in line:
                    print("      " + line.strip()[:150])
    if env:
        print("\n环境受限（不是代码问题）：")
        for r in env:
            print(f"  ! {r['label']} —— SSL 被本机代理拦截，换个网络环境即可")
    if not bad and not env:
        print("全部通过 ✓")
    print("=" * 74)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())