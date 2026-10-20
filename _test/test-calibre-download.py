# -*- coding: utf-8 -*-
"""在本地起一个支持 Range 的 HTTP 服务器，把 calibre 模块的下载链路逐条验证。

覆盖：分片并发下载、取消、断点续传、分片合并、魔数校验失败、force 重下。
全程走 127.0.0.1，不消耗真实跨境流量。
"""
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = os.path.join(HERE, "_cal_tmp")
sys.path.insert(0, ROOT)

MSI = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
SIZE = 40 * 1024 * 1024          # 40 MB 假安装包
CHUNK = 32 * 1024
DELAY = 0.03                     # 每块延迟，制造「慢线路」以便测试取消

PAYLOAD = os.path.join(TMP, "payload.bin")
BAD = os.path.join(TMP, "bad.bin")


def make_payloads():
    os.makedirs(TMP, exist_ok=True)
    for path, head in ((PAYLOAD, MSI), (BAD, b"hello-world")):
        if os.path.isfile(path) and os.path.getsize(path) == SIZE:
            continue
        with open(path, "wb") as f:
            f.write(head + b"\x00" * (8 - len(head)))
            block = os.urandom(1024 * 1024)
            left = SIZE - 8
            while left > 0:
                n = min(len(block), left)
                f.write(block[:n])
                left -= n
    return hashlib.sha256(open(PAYLOAD, "rb").read()).hexdigest()


class RangeHandler(BaseHTTPRequestHandler):
    payload = PAYLOAD
    served = 0

    def log_message(self, *a):
        pass

    def _target(self):
        p = self.path.split("?")[0]
        if p == "/dist/win64":
            return "redirect"
        if p == "/calibre-64bit-9.16.0.msi":
            return "file"
        if p == "/bad.msi":
            return "bad"
        return None

    def _size(self, kind):
        return SIZE

    def _resolve(self, kind):
        return BAD if kind == "bad" else PAYLOAD

    def do_HEAD(self):
        kind = self._target()
        if kind == "redirect":
            self.send_response(302)
            self.send_header("Location", "/calibre-64bit-9.16.0.msi")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not kind:
            self.send_response(404); self.end_headers(); return
        n = os.path.getsize(self._resolve(kind))
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(n))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        kind = self._target()
        if kind == "redirect":
            self.send_response(302)
            self.send_header("Location", "/calibre-64bit-9.16.0.msi")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not kind:
            self.send_response(404); self.end_headers(); return

        path = self._resolve(kind)
        n = os.path.getsize(path)
        rng = self.headers.get("Range")
        start, end = 0, n - 1
        partial = False
        if rng:
            m = re.match(r"bytes=(\d+)-(\d*)", rng.strip())
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else n - 1
                partial = True
        end = min(end, n - 1)
        length = end - start + 1
        if partial and length <= 0:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{n}")
            self.end_headers()
            return

        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{n}")
        self.end_headers()

        with open(path, "rb") as f:
            f.seek(start)
            left = length
            try:
                while left > 0:
                    block = f.read(min(CHUNK, left))
                    if not block:
                        break
                    self.wfile.write(block)
                    left -= len(block)
                    RangeHandler.served += len(block)
                    time.sleep(DELAY)
            except OSError:            # 客户端取消时对端会直接断，属预期
                pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    sha = make_payloads()
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), RangeHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    from kindle import calibre as C

    # 把模块指向本地测试服务器
    C.TOOL_DIR = TMP
    C.ALLOWED_HOSTS = {"127.0.0.1"}
    C.ENTRY_URL = f"http://127.0.0.1:{port}/dist/win64"
    C.CHUNK = 64 * 1024

    fails = []

    def check(name, cond, extra=""):
        print(f"  [{'OK ' if cond else '× '}] {name}  {extra}")
        if not cond:
            fails.append(name)

    def wait(phase_want, timeout=180):
        t0 = time.time()
        while time.time() - t0 < timeout:
            p = C.progress()
            if p["phase"] in phase_want:
                return p
            time.sleep(0.2)
        return C.progress()

    def wipe():
        for n in os.listdir(TMP):
            if n.startswith("calibre"):
                os.remove(os.path.join(TMP, n))

    print("=" * 74)
    print("测试环境：40 MB 假安装包，本地 Range 服务器，模拟慢线路")
    print("=" * 74)

    # ---------- 1. Range 探测 ----------
    print("\n1. Range 探测")
    check("服务器被识别为支持分片", C._supports_range(C.ENTRY_URL.replace("/dist/win64", "/calibre-64bit-9.16.0.msi")))

    # ---------- 2. resolve_latest 跟随重定向 ----------
    print("\n2. 解析最新版（跟随 302）")
    url, name, total = C.resolve_latest()
    check("重定向后 URL 正确", url.endswith("/calibre-64bit-9.16.0.msi"), url)
    check("文件名解析正确", name == "calibre-64bit-9.16.0.msi", name)
    check("体积与本地一致", total == SIZE, f"{total} == {SIZE}")

    # ---------- 3. 全新分片下载 ----------
    print("\n3. 全新下载（4 路分片）")
    wipe()
    RangeHandler.served = 0
    t0 = time.time()
    C.start_download()
    p = wait({"done", "error"})
    dt = time.time() - t0
    final = os.path.join(TMP, "calibre-64bit-9.16.0.msi")
    check("phase = done", p["phase"] == "done", p.get("error", ""))
    check("文件已落盘", os.path.isfile(final))
    check("体积完全一致", os.path.isfile(final) and os.path.getsize(final) == SIZE)
    check("内容 SHA-256 与源一致",
          os.path.isfile(final) and hashlib.sha256(open(final, "rb").read()).hexdigest() == sha)
    check("魔数判定为 msi", C.probe_installer(final) == "msi")
    check("分片临时文件已清理",
          not [n for n in os.listdir(TMP) if ".part" in n], str([n for n in os.listdir(TMP) if ".part" in n]))
    check("进度里记录了 sha256", len(p.get("sha256", "")) == 64)
    check("并行确实生效（服务端发送量 ≈ 体积）",
          SIZE <= RangeHandler.served <= SIZE * 1.2, f"served={RangeHandler.served}")
    print(f"       用时 {dt:.1f}s（若串行约需 {SIZE/CHUNK*DELAY:.1f}s）")

    # ---------- 4. 取消 + 续传 ----------
    print("\n4. 取消 → 续传")
    wipe()
    C.start_download(force=True)
    time.sleep(1.6)
    mid = C.progress()
    check("下载进行中", mid["active"] and mid["downloaded"] > 0,
          f"已下 {mid['downloaded']//1024} KB, {mid['segments']} 路")
    C.cancel_download()
    p = wait({"cancelled", "error", "done"})
    check("取消后 phase = cancelled", p["phase"] == "cancelled", p.get("error", ""))
    parts = sorted(n for n in os.listdir(TMP) if ".part" in n)
    kept = sum(os.path.getsize(os.path.join(TMP, n)) for n in parts)
    check("已下载的部分被保留", kept > 0, f"{kept//1024} KB, {len(parts)} 个分片")
    check("完整文件未生成", not os.path.isfile(final))

    pi = C.partial_info()
    check("partial_info 能报告残留", pi["bytes"] == kept and pi["files"] == len(parts),
          json.dumps(pi))

    RangeHandler.served = 0
    C.start_download()
    early = None
    t0 = time.time()
    while time.time() - t0 < 8:
        q = C.progress()
        if q.get("resumed"):
            early = q
            break
        time.sleep(0.1)
    check("续传时报告了起点", bool(early), f"resumed={early.get('resumed') if early else None}")
    p = wait({"done", "error"})
    check("续传后 phase = done", p["phase"] == "done", p.get("error", ""))
    check("续传结果内容完整",
          os.path.isfile(final) and hashlib.sha256(open(final, "rb").read()).hexdigest() == sha)
    check("续传只补了剩下的（未重下全部）",
          RangeHandler.served < SIZE, f"本次仅收到 {RangeHandler.served//1024} KB / {SIZE//1024} KB")

    # ---------- 5. 魔数校验失败 ----------
    print("\n5. 非安装包应被拒绝")
    wipe()
    C.ENTRY_URL = f"http://127.0.0.1:{port}/bad.msi"
    C.start_download()
    p = wait({"done", "error"})
    check("phase = error", p["phase"] == "error", p.get("error", ""))
    check("错误信息提到安装包", "安装包" in (p.get("error") or ""), p.get("error", ""))
    check("坏文件未留在目录里",
          not [n for n in os.listdir(TMP) if n.lower().endswith((".msi", ".exe"))],
          str(os.listdir(TMP)))

    # ---------- 6. 白名单仍然生效 ----------
    print("\n6. 白名单")
    try:
        C._check_url("https://evil.example.com/x.msi")
        check("非官方域名被拒绝", False)
    except ValueError:
        check("非官方域名被拒绝", True)

    # ---------- 收尾 ----------
    srv.shutdown()
    print("\n" + "=" * 74)
    if fails:
        print(f"失败 {len(fails)} 项：")
        for f in fails:
            print("  ★", f)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    code = main()
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
