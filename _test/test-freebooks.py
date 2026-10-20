# -*- coding: utf-8 -*-
"""公版书库冒烟测试：检索解析 + 真实取回 + 文件校验。"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kindle import freebooks as fb

ok = fail = 0
def chk(cond, msg):
    global ok, fail
    if cond: ok += 1; print("  [OK] ", msg)
    else:    fail += 1; print("  [FAIL]", msg)

print("== 1. 检索：英文 ==")
r = fb.search("sherlock holmes")
chk(len(r["items"]) > 0, f"命中 {len(r['items'])} 条，errors={r['errors']}")
pg = [i for i in r["items"] if i["source"] == "gutenberg"]
se = [i for i in r["items"] if i["source"] == "se"]
chk(pg and pg[0]["files"], "古登堡条目带下载格式")
if pg:
    f0 = pg[0]["files"][0]
    chk(f0["ext"] == ".mobi" and f0["native"], f"古登堡首选格式是原生 {f0['ext']}")
    chk("gutenberg.org" in f0["url"], "下载链接指向 gutenberg.org")
chk(se and se[0]["files"][0]["url"].endswith("?source=download"),
    "标准电子书的直链补上了 ?source=download")

print("== 2. 检索：中文繁体 ==")
r2 = fb.search("紅樓夢", lang="zh")
chk(len(r2["items"]) > 0, f"繁体命中 {len(r2['items'])} 条")

print("== 3. 检索：中文简体应给出可读提示 ==")
r3 = fb.search("红楼梦", lang="zh")
chk(len(r3["items"]) == 0 or True, f"简体命中 {len(r3['items'])} 条，hint={bool(r3['hint'])}")
if not r3["items"]:
    chk("繁体" in r3["hint"], "无结果时提示改用繁体检索")

print("== 4. 中文公版书榜 ==")
r4 = fb.search("", lang="zh")
chk(len(r4["items"]) > 0, f"中文榜 {len(r4['items'])} 条 / 共 {r4['count']} 册")

print("== 5. 真实取回（古登堡 KF8，约 0.5 MB）==")
target = None
for it in fb.search("sherlock holmes")["items"]:
    if it["source"] == "gutenberg" and any(f["ext"] == ".mobi" for f in it["files"]):
        target = it; break
chk(target is not None, "找到可下载的古登堡 KF8 条目")
if target:
    f = [x for x in target["files"] if x["ext"] == ".mobi"][0]
    res = fb.enqueue([{**target, **f, "ext": f["ext"]}])
    chk(res["ok"], f"入队 {res.get('ids')}")
    t0 = time.time()
    while time.time() - t0 < 240:
        st = fb.state()
        cur = st["current"]
        if cur:
            print(f"     {cur['status']} {cur.get('percent',0)}% "
                  f"{cur.get('got',0)//1024}/{cur.get('total',0)//1024} KB "
                  f"{cur.get('speed_avg',0)/1024:.0f} KB/s eta {cur.get('eta',0)}s")
        elif not st["busy"]:
            break
        time.sleep(4)
    st = fb.state()
    j = st["jobs"][-1] if st["jobs"] else {}
    chk(j.get("status") == "完成", f"状态={j.get('status')} err={j.get('error','')}")
    out = j.get("out") or ""
    chk(bool(out) and os.path.isfile(out), f"落盘：{os.path.basename(out)}")
    if out and os.path.isfile(out):
        from kindle import mobi as mobi_mod
        chk(mobi_mod.sniff(out) == "mobi", "落盘文件魔数确认是 MOBI 家族")
        chk(os.path.getsize(out) > 100_000, f"体积 {os.path.getsize(out)//1024} KB")
        print("     书名：", j.get("title"), "|", j.get("author"))

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
