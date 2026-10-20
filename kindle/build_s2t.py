# -*- coding: utf-8 -*-
"""由现有 t2s-* 表反向推导 s2t-* 表（简体→繁体）。

设计要点：
  1. 字符表反转是一对多难题（如 发→發/髮）。我们用「短语证据」给每个简体字
     选一个默认繁体：扫描 t2s-phrases，按字位对齐统计 (简, 繁) 出现次数，
     频次最高的繁体作为默认。这样既数据驱动，又不会拍脑袋。
  2. 若某简体字的候选繁体里本身就包含它自己（即该字繁简同形，如 里/后/干），
     给「同形」候选加权，优先选它当默认 —— 最安全（不改动）。
  3. 极少数短语证据仍不可靠的一对多（发/干/复/历），用 CURATED_OVERRIDE 明示。
  4. s2t-phrases 直接反向 t2s-phrases（简→繁），但只保留一对一，去重。
  5. s2t-fix 不放地域词替换（那是 s2tw 的事），只放最常用的一对多消歧短语，
     优先级最高，保证日常词汇（头发/干净/里面/历史…）转对。

纯标准库，不联网。生成后可直接删掉本脚本。
"""
from __future__ import annotations

import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# 短语证据不可靠、又无法靠「同形加权」兜底的一对多，这里直接拍板。
# 原则：默认选「出错面更小」的那个。
#   - 里：繁简同形（里=里程/公里），默认不转（no-op），只在短语里按「裡」语境转换，
#        避免把 公里/里程/故里 错成 公裡/裡程/故裡。
#   - 后：现代文「后」绝大多数表「之后/后面」，默认→後；皇后/太后 由短语保护为 no-op。
#   - 发/干/复/历：单字默认用最常见的繁体，头发/干活/复杂/日历 等由短语兜底。
CURATED_OVERRIDE = {
    "里": "里",   # no-op；裡 语境走短语
    "发": "發",   # 头发→頭髮 由 s2t-fix 短语负责
    "干": "乾",   # 干活→幹活 由 s2t-fix 短语负责
    "复": "復",   # 复杂→複雜 由 s2t-fix 短语负责
    "历": "歷",   # 日历→日曆 由 s2t-fix 短语负责
}

# 最高优先级：简→繁 常用词消歧。覆盖日常阅读里最容易错的一对多。
# 注意：[里] 默认 no-op，所以所有「裡」语境都要列成短语；[后] 默认→後，
# 所以皇后/太后 等要列成 no-op 短语保护。
S2T_FIX = [
    # —— 里 / 裡 语境（默认 no-op，这里显式转裡）——
    "里面\t裡面", "这里\t這裡", "那里\t那裡", "哪里\t哪裡", "心里\t心裡",
    "家里\t家裡", "手里\t手裡", "夜里\t夜裡", "城里\t城裡", "怀里\t懷裡",
    "眼里\t眼裡", "梦里\t夢裡", "往里\t往裡", "从里\t從裡", "向里\t向裡",
    "暗里\t暗裡", "内里\t內裡", "私下里\t私下裡", "底里\t底裡", "屋里\t屋裡",
    "队里\t隊裡", "班里\t班裡", "房里\t房裡", "村里\t村裡", "锅里\t鍋裡",
    "兜里\t兜裡", "背里\t背裡", "海底里\t海底裡", "心眼里\t心眼裡",
    # —— 后 / 後：皇后、太后 等「后」本就是繁体，保护为 no-op ——
    "皇后\t皇后", "太后\t太后", "王后\t王后", "皇太后\t皇太后",
    # —— 头发 / 干 等一对多 ——
    "头发\t頭髮", "干净\t乾淨", "干活\t幹活", "后面\t後面", "历史\t歷史",
    "日历\t日曆", "恢复\t恢復", "复杂\t複雜", "了解\t瞭解", "出发\t出發",
    "发展\t發展", "国家\t國家", "时间\t時間", "问题\t問題", "电脑\t電腦",
    "手机\t手機", "音乐\t音樂", "电影\t電影", "学校\t學校", "我们\t我們",
    "你们\t你們", "他们\t他們", "什么\t什麼", "怎么\t怎麼", "为什么\t為什麼",
    "时候\t時候", "东西\t東西", "觉得\t覺得", "应该\t應該", "因为\t因為",
    "已经\t已經", "告诉\t告訴", "谢谢\t謝謝", "认识\t認識", "机会\t機會",
    "说话\t說話", "介绍\t介紹", "环境\t環境", "表示\t表示", "关系\t關係",
    "系统\t系統", "网络\t網絡", "节目\t節目", "质量\t質量", "标准\t標準",
    "经验\t經驗", "现实\t現實", "情况\t情況", "生活\t生活", "工作\t工作",
    "世界\t世界",
]


def read_chars(path):
    m = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if len(line) >= 2:
                m[line[0]] = line[1]
    return m


def read_phrases(path):
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 2 and parts[0] and parts[1]:
                out[parts[0]] = parts[1]
    return out


def main():
    t2s_chars = read_chars(os.path.join(DATA, "t2s-chars.txt"))
    t2s_phrs = read_phrases(os.path.join(DATA, "t2s-phrases.txt"))

    # 反向字符：简 → 候选繁体列表（保序去重）
    rev: dict[str, list[str]] = {}
    for trad, simp in t2s_chars.items():
        rev.setdefault(simp, [])
        if trad not in rev[simp]:
            rev[simp].append(trad)

    # 短语证据：按字位对齐统计 (简, 繁) 频次
    evid: dict[str, Counter] = {}
    for trad, simp in t2s_phrs.items():
        if len(trad) == len(simp):
            for s, t in zip(simp, trad):
                evid.setdefault(s, Counter())[t] += 1

    # 选默认繁体
    s2t_chars: dict[str, str] = {}
    for simp, cands in rev.items():
        if len(cands) == 1:
            s2t_chars[simp] = cands[0]
            continue
        if simp in CURATED_OVERRIDE:
            s2t_chars[simp] = CURATED_OVERRIDE[simp]
            continue
        scored = []
        for c in cands:
            score = evid.get(simp, Counter()).get(c, 0)
            if c == simp:          # 同形候选加权，优先不改动
                score += 1000
            scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        s2t_chars[simp] = scored[0][1]

    # 反向短语：简→繁，去重（多繁对一简时取首个）
    s2t_phrs: dict[str, str] = {}
    for trad, simp in t2s_phrs.items():
        if simp not in s2t_phrs:
            s2t_phrs[simp] = trad

    # 写出 s2t-chars.txt（两字相邻，繁在右）
    with open(os.path.join(DATA, "s2t-chars.txt"), "w", encoding="utf-8") as f:
        for simp, trad in sorted(s2t_chars.items()):
            f.write(simp + trad + "\n")

    # 写出 s2t-phrases.txt（简\t繁）
    with open(os.path.join(DATA, "s2t-phrases.txt"), "w", encoding="utf-8") as f:
        for simp, trad in sorted(s2t_phrs.items()):
            f.write(f"{simp}\t{trad}\n")

    # 写出 s2t-fix.txt（简\t繁，最高优先级）
    with open(os.path.join(DATA, "s2t-fix.txt"), "w", encoding="utf-8") as f:
        for line in S2T_FIX:
            f.write(line + "\n")

    # 报告
    ambig = {k: v for k, v in rev.items() if len(v) > 1}
    print(f"s2t-chars.txt  : {len(s2t_chars)} 条")
    print(f"s2t-phrases.txt: {len(s2t_phrs)} 条")
    print(f"s2t-fix.txt    : {len(S2T_FIX)} 条")
    print(f"反转时的一对多简体字共 {len(ambig)} 个，默认选择已落定")
    print("示例默认：")
    for k in ["发", "干", "后", "里", "复", "历", "范", "余"]:
        if k in s2t_chars:
            print(f"  {k} → {s2t_chars[k]}")


if __name__ == "__main__":
    main()
