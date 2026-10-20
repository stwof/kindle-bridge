# -*- coding: utf-8 -*-
"""端口占用场景测试（进程内 mock，不起真进程）：
  A. 端口被健康的 Kindle 桥占着 -> 打印提示、不开浏览器、正常退出
  B. 端口被无关程序占用 -> 自动换下一个端口
  C. _bridge_alive 判别
"""
import contextlib
import io
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app                                               # noqa: E402

ok = fail = 0
def chk(cond, msg):
    global ok, fail
    if cond: ok += 1; print("  [OK]  ", msg)
    else:    fail += 1; print("  [FAIL]", msg)


class Boom(Exception):
    pass


class FakeServer:
    def __init__(self, addr, handler):
        self.addr = addr
        raise Boom("不应被调用")

class OkServer:
    last = None
    def __init__(self, addr, handler):
        self.addr = addr
        OkServer.last = addr
    def serve_forever(self):
        pass
    def server_close(self):
        pass


print("== C. _bridge_alive 判别 ==")
chk(app._bridge_alive("http://127.0.0.1:8765/"), "正在运行的服务被识别为 Kindle 桥")
chk(not app._bridge_alive("http://127.0.0.1:1/"), "连不上的端口判为否")

print("== A. 端口被健康桥占用 -> 友好退出 ==")
app.ThreadingHTTPServer = lambda addr, h: (_ for _ in ()).throw(OSError("[WinError 10048]"))
buf = io.StringIO()
opened = []
app.webbrowser.open = lambda u: opened.append(u) or True
with contextlib.redirect_stdout(buf):
    sys.argv = ["app.py", "--port", "8765", "--no-browser"]
    app.main()
out = buf.getvalue()
chk("已有 Kindle 桥在运行" in out, f"提示语正确: {out.strip().splitlines()[:1]}")
chk(not opened, "--no-browser 时不弹浏览器")

print("== B. 端口被无关程序占用 -> 自动换端口 ==")
s = socket.socket()
s.bind(("127.0.0.1", 0))
FREE_PORT = s.getsockname()[1]
s.listen(1)                                               # 占住一个空闲端口

calls = {"n": 0}
def flaky(addr, h):
    calls["n"] += 1
    if addr[1] == FREE_PORT:
        raise OSError("[WinError 10048] 被占")
    return OkServer(addr, h)

app.ThreadingHTTPServer = flaky
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    sys.argv = ["app.py", "--port", str(FREE_PORT), "--no-browser"]
    app.main()
out = buf.getvalue()
chk(OkServer.last and OkServer.last[1] == FREE_PORT + 1,
    f"换到 {FREE_PORT + 1} 端口（实测 {OkServer.last and OkServer.last[1]}）")
chk(f"被其他程序占用" in out, "有占用提示")
s.close()

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
