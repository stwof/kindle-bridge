# -*- coding: utf-8 -*-
"""简繁转换 —— 主引擎 OpenCC，原自制表兜底，双向（简↔繁）+ 自动判别。

为什么用 OpenCC：古登堡的中文藏书几乎全是**繁体**（古典小说居多，
且多由港台或海外志愿者数字化），而这套书的目标读者习惯简体；
反过来也有人手上是简体 txt/epub，想在 Kindle（KOReader）上看繁体。
所以这里同时支持 繁→简 与 简→繁，并能自动判别一份文件到底是哪边。

字典来源 = OpenCC（BYVoid 开源的中文字转换项目，事实标准）：
  - 数据表 7000+ 字 + 大量词组，覆盖《警世通言》这类古典小说里
    「捲→卷 / 擡→抬 / 舖→铺 / 逕→径 / 牀→床 / 啟→启」等冷僻对应，
    远胜本项目早先自制的反向推导表（只覆盖约 3500 条，漏转明显）。
  - 以纯 Python 重新实现打包（opencc-python-reimplemented），自带数据、
    无需编译器、离线可用，符合本项目「拷进去就能用」的原则。
  - 支持多种地区变体（s2tw / s2hk / s2twp 等），如需港台正字可扩展。
  - 简→繁 默认用 **s2twp（台湾正体·含词组）**：输出「裡面 / 網路 / 軟體 /
    資訊 / 這裡」这类最贴近繁体读物习惯的形式；繁→简 用标准 **t2s**。

兜底策略：若运行环境未能装上 opencc（极少数情况），自动回退到
项目自带的 t2s / s2t 表（data/ 下），保证功能不中断、只是准确率下降。

对外公开函数（API 稳定，epub.py / zhconv_file.py 直接调用）：
  to_simplified(text) / to_traditional(text) / convert(text, to) /
  detect(text) / is_traditional(text) / ratio_of(text) / looks_chinese(text) /
  available() / backend()
"""
from __future__ import annotations

import os
import re

from . import paths as _paths

# 词表是只读资源：冻结成 exe 后它躺在解包目录里，所以走 resource_dir()。
DATA_DIR = os.path.join(_paths.resource_dir(), "kindle", "data")

# 中日韩统一表意文字（含扩展 A）。用它做全文件扫描，比逐字符快一个数量级。
_CJK_RE = re.compile("[㐀-鿿䶀-䶿]")

# ---- OpenCC 主引擎 -------------------------------------------------------
try:                                    # 优先使用开源 OpenCC（完整字典）
    from opencc import OpenCC
    _CC_AVAILABLE = True
except Exception:                       # 极少数环境装不上，回退自制表
    OpenCC = None
    _CC_AVAILABLE = False

_CC_T2S = "t2s"       # 繁 -> 简（标准）
_CC_S2T = "s2twp"    # 简 -> 繁（台湾正体·含词组，读繁体书最自然）
_cc_t2s = None
_cc_s2t = None


def _cc_init() -> None:
    global _cc_t2s, _cc_s2t
    if not _CC_AVAILABLE or _cc_t2s is not None:
        return
    try:
        _cc_t2s = OpenCC(_CC_T2S)
        _cc_s2t = OpenCC(_CC_S2T)
    except Exception:
        _cc_t2s = _cc_s2t = None


# OpenCC 标准数据仍漏掉的少量冷僻 / 异体字，用「异体 → 标准」补丁补全。
# 只在 OpenCC 未能转换的字符上生效（translate 只动补丁里的键），
# 绝不干扰 OpenCC 的词典/语境判断（例如 乾坤 的「乾」不会因此被误改成「干」）。
_SUPP_T2S = {
    "擡": "抬", "舖": "铺", "恠": "怪", "竝": "并", "靑": "青", "睂": "眉",
    "羣": "群", "旾": "春", "迃": "迂", "秌": "秋", "僊": "仙", "巖": "岩",
    "涙": "泪", "棄": "弃", "異": "异", "週": "周", "甦": "苏", "麪": "面",
    "菓": "果", "卽": "即", "効": "效", "刄": "刃", "兎": "兔", "砲": "炮",
    "羮": "羹", "谿": "溪", "虖": "呼", "艸": "草", "咊": "和", "灋": "法",
    "栞": "刊", "祕": "秘", "竪": "竖", "甆": "瓷", "敓": "夺", "敍": "叙",
    "煑": "煮", "煖": "暖", "烖": "灾", "玅": "妙", "盡": "尽", "盃": "杯",
    "眞": "真", "竝": "并", "筭": "算", "罸": "罚", "羗": "羌",
    "苧": "苎",   # 薴→苧 是 OpenCC 的第一跳，苧→苎 这一跳它不做（单次转换不链式）
}
# 简 -> 繁 方向直接用 OpenCC s2twp（已覆盖 裡面/抬頭鋪子/網路軟體 等，
# 且「标准简体→异体」不能靠自动反向生成——会产出错误繁体如 面→麪），故留空。
# 若日后确需补全某个 s2twp 漏掉的简→繁字，请在此手动、谨慎添加 简:繁 配对。
_SUPP_S2T: dict[str, str] = {}
_SUPP_T2S_TABLE = {ord(k): v for k, v in _SUPP_T2S.items()}
_SUPP_S2T_TABLE = {ord(k): v for k, v in _SUPP_S2T.items()}

# 「按语义保留繁体」的词：这些词里的字**不能**按字符表一刀切。
# 例：五声音阶「宫商角徵羽」里的「徵」(zhǐ) 不是「征」；
#     OpenCC 的短语表收了「宫商角徵羽」却没收「變徵」，于是把「變徵之聲」
#     错转成「变征之声」。这里的做法是：转换前用哨兵把整个词保护起来，
#     转换后再还原成预先指定的正确写法。
_T2S_KEEP: dict[str, str] = {
    "變徵": "变徵",
    # 乾坤 的「乾」(qián) 不是「干」；五声音阶「宫商角徵羽」的「徵」(zhǐ)
    # 不是「征」。OpenCC 的短语表本身会保留它们；这里让自制表兜底路径
    # 也遵守同样的语义（见 to_simplified 的兜底分支）。
    "乾坤": "乾坤",
    "宫商角徵羽": "宫商角徵羽",
    "變徵之聲": "变徵之声",
}
_SENT_A = "\ue000"
_SENT_B = "\ue001"
_KEEP_RE = None


def _keep_re():
    global _KEEP_RE
    if _KEEP_RE is None and _T2S_KEEP:
        keys = sorted(_T2S_KEEP, key=len, reverse=True)
        _KEEP_RE = re.compile("|".join(re.escape(k) for k in keys))
    return _KEEP_RE


def _protect(text: str, mapping: dict[str, str]) -> tuple[str, list[str]]:
    """把需要保留的词换成哨兵，返回 (带哨兵的文本, 还原用的成品列表)。"""
    rx = _keep_re()
    if not rx or not text:
        return text, []
    store: list[str] = []

    def _sub(m):
        store.append(mapping[m.group(0)])
        return f"{_SENT_A}{len(store) - 1}{_SENT_B}"

    return rx.sub(_sub, text), store


def _restore(text: str, store: list[str]) -> str:
    for i, val in enumerate(store):
        text = text.replace(f"{_SENT_A}{i}{_SENT_B}", val)
    return text


def backend() -> str:
    """当前实际使用的转换内核：'opencc' 或 'tables'。便于前端/日志展示。"""
    _cc_init()
    return "opencc" if _cc_t2s is not None else "tables"


# ---- 自制表引擎（兜底） ---------------------------------------------------
class _Dir:
    """一个转换方向（t2s 或 s2t）的全部数据。"""

    __slots__ = ("name", "chars", "phrases", "heads", "maxphr", "table")

    def __init__(self, name, chars, phrases):
        self.name = name
        self.chars = chars
        self.phrases = phrases                 # 已含 fix 覆盖，优先级最高
        self.heads = {k[0] for k in phrases if k}
        self.maxphr = max((len(k) for k in phrases), default=0)
        self.table = {ord(k): v for k, v in chars.items()}


_T2S: _Dir | None = None
_S2T: _Dir | None = None
_TRAD_ONLY: set[str] = set()
_SIMP_ONLY: set[str] = set()


def _load_chars(file):
    m: dict[str, str] = {}
    try:
        with open(os.path.join(DATA_DIR, file), "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if len(line) >= 2:
                    m[line[0]] = line[1]
    except OSError:
        m = {}
    return m


def _load_phrases(files):
    """读短语表；多个文件按序载入，后面的覆盖前面的（fix 最后载入 = 优先级最高）。"""
    out: dict[str, str] = {}
    for fn in files:
        try:
            with open(os.path.join(DATA_DIR, fn), "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) == 2 and parts[0] and parts[1]:
                        out[parts[0]] = parts[1]
        except OSError:
            pass
    return out


def _load() -> None:
    global _T2S, _S2T, _TRAD_ONLY, _SIMP_ONLY
    if _T2S is not None:
        return

    t2s_chars = _load_chars("t2s-chars.txt")
    t2s_phrs = _load_phrases(["t2s-phrases.txt", "t2s-fix.txt"])
    _T2S = _Dir("t2s", t2s_chars, t2s_phrs)

    s2t_chars = _load_chars("s2t-chars.txt")
    s2t_phrs = _load_phrases(["s2t-phrases.txt", "s2t-fix.txt"])
    _S2T = _Dir("s2t", s2t_chars, s2t_phrs)

    # 判别字：只在繁体里出现的字（是 t2s 的键不是值）、只在简体里出现的字（是值不是键）。
    keys, vals = set(t2s_chars), set(t2s_chars.values())
    _TRAD_ONLY = keys - vals
    _SIMP_ONLY = vals - keys


def available() -> bool:
    """任一引擎可用即可。"""
    if backend() == "opencc":
        return True
    _load()
    return bool(_T2S and _T2S.chars)


def _convert(text: str, d: _Dir) -> str:
    """按方向 d 做短语优先 + 字符兜底转换（仅兜底引擎使用）。"""
    if not text:
        return text
    _load()
    if not d.chars:
        return text

    parts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(text)

    while i < n:
        ch = text[i]
        if ch in d.heads:
            hit = None
            for length in range(min(d.maxphr, n - i), 1, -1):
                v = d.phrases.get(text[i:i + length])
                if v:
                    hit = (v, length)
                    break
            if hit:
                if buf:
                    parts.append("".join(buf).translate(d.table))
                    buf = []
                parts.append(hit[0])
                i += hit[1]
                continue
        buf.append(ch)
        i += 1

    if buf:
        parts.append("".join(buf).translate(d.table))
    return "".join(parts)


# ---- 公开转换入口（OpenCC 主，表兜底） -----------------------------------
def to_simplified(text: str) -> str:
    """繁体 → 简体。OpenCC 主引擎 + 冷僻/异体补丁 + 语义保留短语。"""
    _cc_init()
    if _cc_t2s is not None:
        try:
            guarded, store = _protect(text, _T2S_KEEP)
            out = _cc_t2s.convert(guarded).translate(_SUPP_T2S_TABLE)
            return _restore(out, store)
        except Exception:
            pass
    _load()
    # 兜底表同样要走「语义保留」和「冷僻/异体补丁」：
    # 否则 乾坤→干坤、宫商角徵羽→宫商角征羽、薴→苧（链式断在苎）都会错。
    guarded, store = _protect(text, _T2S_KEEP)
    out = _convert(guarded, _T2S).translate(_SUPP_T2S_TABLE)
    return _restore(out, store)


def to_traditional(text: str) -> str:
    """简体 → 繁体。OpenCC 主引擎 + 冷僻/异体补丁。"""
    _cc_init()
    if _cc_s2t is not None:
        try:
            return _cc_s2t.convert(text).translate(_SUPP_S2T_TABLE)
        except Exception:
            pass
    _load()
    return _convert(text, _S2T)


def convert(text: str, to: str = "auto") -> str:
    """统一入口。

    to:
      "simplified" / "简体" / "simp"   → 转成简体
      "traditional" / "繁体" / "trad" → 转成繁体
      "auto"                          → 自动判别当前字体，再转成相反的那边
    """
    to = (to or "auto").strip().lower()
    if to in ("traditional", "繁体", "trad"):
        return to_traditional(text)
    if to in ("simplified", "简体", "simp"):
        return to_simplified(text)
    # auto：已经是目标字体的书不做任何改动（简→繁再简回来只会把「头发」变成「头發」）
    if is_traditional(text):
        return to_simplified(text)
    return to_traditional(text)


# ---- 字体判别（用自制表集合，O(1) 查表，足够决定方向） -------------------
def ratio_of(text: str, limit: int = 0) -> float:
    """这段文字里，可判别的字有多少是繁体。返回 0~1；无判别依据时返回 0.5。

    limit 用来只看前 N 个字符 —— 90 万字的书没必要全扫，取样就够准。
    """
    _load()
    sample = text[:limit] if limit else text
    if not sample or not _TRAD_ONLY:
        return 0.5
    t = s = 0
    for c in sample:
        if c in _TRAD_ONLY:
            t += 1
        elif c in _SIMP_ONLY:
            s += 1
    if t + s == 0:
        return 0.5
    return t / (t + s)


def is_traditional(text: str, limit: int = 65536, threshold: float = 0.5) -> bool:
    """这份文件是繁体的吗？已经是简体就别动它。"""
    return ratio_of(text, limit) > threshold


def detect(text: str, limit: int = 65536) -> str:
    """判别文本字体：'traditional' / 'simplified' / 'unknown'。"""
    _load()
    sample = text[:limit] if limit else text
    if not sample or not _TRAD_ONLY:
        return "unknown"
    t = s = 0
    for c in sample:
        if c in _TRAD_ONLY:
            t += 1
        elif c in _SIMP_ONLY:
            s += 1
    if t + s == 0:
        return "unknown"
    if t > s:
        return "traditional"
    if s > t:
        return "simplified"
    return "unknown"


def looks_chinese(text: str) -> bool:
    """有没有中文字。没有的话转换纯属浪费时间。

    用编译好的正则全文件搜，是 C 实现，比 Python 逐字符快得多，
    所以不用为了省时间只扫开头 —— 只看开头会漏掉「前面是英文前言、
    正文从第三页才开始」的书。
    也不能要求「至少 8 个字」才算中文：OPF 元数据里书名+作者常常只有三四个字，
    那样会把元数据整份跳过，结果正文转了、书名没转。
    """
    return _CJK_RE.search(text) is not None
