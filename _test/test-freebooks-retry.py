# -*- coding: utf-8 -*-
"""断点续传 + 重试机制测试：本地 HTTP 源，不碰外网。

场景：
  A. 预置 3/4 个分片在缓存目录 -> _run_job 应只补第 4 片并完成校验、落盘
  B. 源站中途掐线 -> 任务失败但分片保留，且被标记为可自动重试
  C. retry() 能把失败任务重新排队
"""
import http.server
import os
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kindle import freebooks as fb                      # noqa: E402
import importlib.util                                   # noqa: E402
_spec = importlib.util.spec_from_file_location(
    "test_mobi_helper", os.path.join(os.path.dirname(os.path.abspath(__file__)), "test-mobi.py"))
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
build_mobi = _m.build_mobi

ok = fail = 0
def chk(cond, msg):
    global ok, fail
    if cond: ok += 1; print("  [OK]  ", msg)
    else:    fail += 1; print("  [FAIL]", msg)

# ---------- 本地源：一个支持 Range 的 600 KB 假 MOBI ----------
_mobi = build_mobi("测试书", "测试作者")
PAD = b"\x00" * (600 * 1024 - len(_mobi))
PAYLOAD = _mobi + PAD
assert len(PAYLOAD) >= 512 * 1024, "要超过 SEGMENT_MIN 才会走分片路径"
KILL_AFTER = None          # 非 None 时，响应这么多字节就掐线

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        rng = self.headers.get("Range", "")
        start, end = 0, len(PAYLOAD) - 1
        if rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a)
            if b:
                end = min(int(b), end)
        n = end - start + 1
        if KILL_AFTER is not None:
            n = min(n, KILL_AFTER)                        # 模拟线路抖动：每次都掐
        self.send_response(206 if rng else 200)
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(PAYLOAD)}")
        self.send_header("Content-Length", str(n))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(PAYLOAD[start:start + n])
        if KILL_AFTER is not None:
            self.wfile.flush()
            self.connection.close()                       # 硬掐
    do_HEAD = do_GET
    def log_message(self, *a):
        pass

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{PORT}/book.mobi"

# 收书目录指到临时位置，别污染真实的「收书」
REAL_INBOX = fb.INBOX_DIR
TEST_INBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out-freebooks-retry")
fb.INBOX_DIR = TEST_INBOX

def new_job(jid):
    job = {"id": jid, "title": "测试书", "author": "测试", "source_name": "本地",
           "url": URL, "ext": ".mobi", "push": False, "status": "排队",
           "got": 0, "total": 0, "percent": 0, "speed": 0.0, "speed_avg": 0.0,
           "eta": 0, "error": "", "out": "", "queued": fb._now()}
    fb._JOBS[jid] = job
    fb._ORDER.append(jid)
    return job

job = new_job(f"{int(time.time())}-1")
tmp = os.path.join(fb.CACHE_DIR, job["id"])
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp)
plan = fb._plan(len(PAYLOAD), fb.SEGMENTS)
for i, (s, e) in enumerate(plan[:-1]):                    # 预置前 3 片（完整）
    with open(os.path.join(tmp, f"part{i}"), "wb") as f:
        f.write(PAYLOAD[s:e + 1])

print("== A. 预置 3/4 分片，续传第 4 片 ==")
job = new_job(f"{int(time.time())}-1")
fb._run_job(job)
chk(job["status"] == "完成", f"状态={job['status']} err={job.get('error','')}")
chk(bool(job.get("out")) and os.path.isfile(job["out"]), f"落盘 {job.get('out_name')}")
if job.get("out") and os.path.isfile(job["out"]):
    chk(open(job["out"], "rb").read() == PAYLOAD, "内容与源逐字节一致")
chk(not os.path.isdir(tmp), "成功后临时分片目录已清掉")

print("== B. 源站持续掐线 -> 分片重试 4 次仍失败 -> 分片保留 + 标记自动重试 ==")
job2 = new_job(f"{int(time.time())}-2")
tmp2 = os.path.join(fb.CACHE_DIR, job2["id"])
try:
    KILL_AFTER = 20 * 1024                    # 单片约 153 KB，每次只给 20 KB：4 次重试必然不够
    fb._run_job(job2)
finally:
    KILL_AFTER = None
chk(job2["status"] in ("失败", "自动重试排队"), f"状态={job2['status']} err={job2.get('error','')[:70]}")
parts = [p for p in os.listdir(tmp2) if p.startswith("part")] if os.path.isdir(tmp2) else []
chk(len(parts) > 0, f"失败后保留了 {len(parts)} 个分片（断点还在）")

print("== C. 手动 retry() 重新排队并跑完 ==")
fb._ensure_worker = lambda: None            # 测试里直接手动跑，别让后台 worker 抢任务
r = fb.retry(job2["id"])
chk(r.get("ok") and job2["id"] in r.get("retried", []), f"retry 返回 {r}")
fb._run_job(job2)
chk(job2["status"] == "完成", f"续传后状态={job2['status']} err={job2.get('error','')}")
if job2["status"] == "完成" and job2.get("out"):
    chk(open(job2["out"], "rb").read() == PAYLOAD, "续传后内容完整")

print("== D. retry() 空手 ==")
chk(fb.retry("nope")["ok"] is False, "对不存在的 id 返回 ok=False")

for jid in list(fb._ORDER):
    fb._JOBS.pop(jid, None)
    fb._ORDER.remove(jid)
    shutil.rmtree(os.path.join(fb.CACHE_DIR, jid), ignore_errors=True)
fb.INBOX_DIR = REAL_INBOX
shutil.rmtree(TEST_INBOX, ignore_errors=True)
srv.shutdown()

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
