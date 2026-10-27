# -*- coding: utf-8 -*-
"""公版书库 —— 从古登堡 / 标准电子书 / Open Library / 维基文库取回无 DRM 的公版书，直接投进 Kindle。

四个源的内容都属公有领域（或开放的 CC / 公版全文），合法、免费、无 DRM：

  · 古登堡计划 Project Gutenberg  7.5 万+ 册，含 444 册中文（紅樓夢、西遊記…）
      走 Gutendex 的 JSON 接口，不需要注册、不需要密钥。
  · 标准电子书 Standard Ebooks    志愿者精校版，排版明显好于古登堡
  · Open Library                  元数据 / 封面极佳，带 Internet Archive 全文扫描
  · 维基文库 Wikisource           志愿者逐字校对的公版全文，官方工具导出 EPUB

下面这些结论都是逐字节实测出来的，不是照抄文档：

  · 古登堡的「Kindle」格式真相是 KF8 —— 链接 .../1661.kf8.images 会 302 到
    pg1661-images-kf8.mobi，Content-Type 为 application/x-mobipocket-ebook，
    魔数是 Palm DB 的 BOOKMOBI。设备原生可读，拷进 documents/ 就行。
  · 标准电子书的 .azw3 直链第一次请求拿到的是「下载已开始」那张 HTML 页
    （Content-Type: application/xhtml+xml）。必须补上 ?source=download 才是
    真文件（application/x-mobi8-ebook，Palm DB 头）。EPUB 同理。
  · 两个源都支持 HTTP Range（返回 206 + Content-Range），所以能分片并发 + 断点续传。
  · 本机实测：古登堡单连接约 14 KB/s，标准电子书约 6 KB/s —— 跨境确实慢，
    因此默认开 4 路分片，并把进度实时报给前端。
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from . import classics as classics_mod
from . import epub as epub_mod
from . import mobi as mobi_mod
from .convert import find_ebook_convert
from . import paths as _paths

BASE_DIR = _paths.data_dir()
INBOX_DIR = os.path.join(BASE_DIR, "收书")
CACHE_DIR = os.path.join(BASE_DIR, "工具", "缓存")

UA = "KindleBridge/1.2 (personal local tool; non-commercial)"
GUTENDEX = "https://gutendex.com/books/"
SE_LIST = "https://standardebooks.org/ebooks"
SE_BASE = "https://standardebooks.org"

# Open Library：元数据与封面极佳的公有领域书目，且大多带 Internet Archive 全文扫描。
OL_SEARCH = "https://openlibrary.org/search.json"
# 维基文库：志愿者逐字校对的公有领域全文，可直接导出 EPUB。
WS_API = "https://{sub}.wikisource.org/w/api.php"
WS_EXPORT = "https://ws-export.wmcloud.org/"

# Open Library 用 MARC 3 字母语言码过滤；只映射界面给出的两种。
_OL_LANG = {"en": "eng", "zh": "chi"}
# 把 MARC 码翻回两字母显示用（覆盖常见项；其余原样保留）
_OL_LANG_SHOW = {
    "eng": "en", "chi": "zh", "fre": "fr", "ger": "de", "spa": "es", "ita": "it",
    "rus": "ru", "por": "pt", "jpn": "ja", "kor": "ko", "dut": "nl", "swe": "sv",
    "dan": "da", "fin": "fi", "pol": "pl", "nor": "no", "hun": "hu", "cze": "cs",
    "gre": "el", "tur": "tr", "ara": "ar", "heb": "he", "hin": "hi", "vie": "vi",
}
# 维基文库按语言分站；界面只用到中/英
_WS_SUB = {"zh": "zh", "en": "en"}

SEGMENTS = 4                      # 分片数：实测 4 路比单连接快 1.6~3 倍
CHUNK = 64 * 1024
SEGMENT_MIN = 512 * 1024          # 小于这个体积不值得分片，单流更省事
SEARCH_TTL = 900.0               # 公版书目几乎不变，缓存久一点，也少给源站添压力
SEARCH_TIMEOUT = 20.0            # 这是「多久没收到一点数据就算卡死」，不是总耗时预算
SEARCH_DEADLINE = 25.0           # 单次检索最多等这么久；等不到就先用已到的结果
PROBE_TIMEOUT = 15.0
READ_TIMEOUT = 30.0
SEARCH_TIMEOUT_FAST = 10.0    # 新接入源在受限网络下易挂起，给更短超时快速失败，不拖累整体检索
MAX_BYTES = 150 * 1024 * 1024

_PG_MOBI = "application/x-mobipocket-ebook"
_PG_EPUB = "application/epub+zip"

SOURCES = [
    {"id": "all", "name": "全部"},
    {"id": "gutenberg", "name": "古登堡计划"},
    {"id": "se", "name": "标准电子书"},
    {"id": "openlibrary", "name": "Open Library"},
    {"id": "wikisource", "name": "维基文库"},
    {"id": "classics", "name": "中文经典"},
]

LANGS = [
    {"id": "", "name": "全部语言"},
    {"id": "zh", "name": "中文"},
    {"id": "en", "name": "英文"},
]


class FreeError(Exception):
    """取书过程中的可预期错误（网络、源站改版、体积超限…）。"""


# ---------------------------------------------------------------- 检索

_SEARCH_CACHE: dict[tuple, tuple[float, dict]] = {}
_SEARCH_LOCK = threading.Lock()
_DISK_CACHE = os.path.join(CACHE_DIR, "检索缓存.json")


def _disk_key(q: str, source: str, lang: str, page: int) -> str:
    return f"{q}|{source}|{lang}|{page}"


def _disk_read(key: str) -> dict | None:
    """断网时还能翻到上次搜过的那批书 —— 是这个工具在跨境弱网下最实用的一层兜底。"""
    if not os.path.isfile(_DISK_CACHE):
        return None
    try:
        with open(_DISK_CACHE, "r", encoding="utf-8") as f:
            blob = json.load(f)
        hit = blob.get(key)
        return hit.get("data") if hit else None
    except (OSError, ValueError):
        return None


def _disk_write(key: str, data: dict) -> None:
    if not data.get("items"):
        return
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        blob = {}
        if os.path.isfile(_DISK_CACHE):
            try:
                with open(_DISK_CACHE, "r", encoding="utf-8") as f:
                    blob = json.load(f)
            except (OSError, ValueError):
                blob = {}
        blob[key] = {"at": time.time(), "data": data}
        if len(blob) > 80:                      # 只留最近的 80 次检索
            for k in sorted(blob, key=lambda k: blob[k].get("at", 0))[:-80]:
                blob.pop(k, None)
        with open(_DISK_CACHE, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False)
    except OSError:
        pass


def _get(url: str, timeout: float = READ_TIMEOUT, tries: int = 3) -> bytes:
    """带重试的 GET。跨境线路实测会间歇性超时 / 503，一次失败不代表源站挂了。"""
    last: FreeError | None = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as f:
                return f.read()
        except urllib.error.HTTPError as ex:
            if ex.code not in (429, 500, 502, 503, 504):
                raise FreeError(f"源站返回 HTTP {ex.code}") from ex
            last = FreeError(f"源站暂时不可用（HTTP {ex.code}），稍后再试")
        except urllib.error.URLError as ex:
            last = FreeError(f"连不上源站：{ex.reason}")
        except TimeoutError:
            last = FreeError("源站响应超时（跨境线路较慢，可稍后重试）")
        except OSError as ex:
            # gaierror 等连接层错误（如域名解析失败）也归为此类，确保单源检索时能正确上报
            last = FreeError(f"连不上源站：{ex}")
        if attempt < tries - 1:
            time.sleep(1.5 * (attempt + 1))
    raise last or FreeError("取数失败")


def _author_names(authors: list) -> str:
    out = []
    for a in authors or []:
        n = (a.get("name") or "").strip()
        if not n:
            continue
        if "," in n:                       # 古登堡是「Austen, Jane」这种写法
            parts = [p.strip() for p in n.split(",", 1)]
            n = " ".join(p for p in (parts[1], parts[0]) if p)
        out.append(n)
    return "、".join(out[:3]) or "佚名"


def _gutenberg(q: str, lang: str, page: int) -> dict:
    params = {"page": str(max(1, page))}
    if q:
        params["search"] = q
    if lang:
        params["languages"] = lang
    url = GUTENDEX + "?" + "&".join(f"{k}={urllib.parse.quote(v)}" for k, v in params.items())
    try:
        raw = json.loads(_get(url, timeout=SEARCH_TIMEOUT, tries=3).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as ex:
        raise FreeError("源站返回的 JSON 无法解析") from ex

    items = []
    for b in raw.get("results") or []:
        fmts = b.get("formats") or {}
        files = []
        if fmts.get(_PG_MOBI):
            files.append({
                "label": "Kindle 原生 · KF8", "ext": ".mobi", "native": True,
                "url": fmts[_PG_MOBI],
                "note": "拷进 documents/ 即读，零转换、零等待",
            })
        if fmts.get(_PG_EPUB):
            files.append({
                "label": "EPUB", "ext": ".epub", "native": False,
                "url": fmts[_PG_EPUB],
                "note": "Kindle 不认 EPUB，需走路线 A 转 AZW3 或路线 B 送信",
            })
        # 古登堡的中文书几乎全是繁体，单独给一条「转简体再排 AZW3」的路
        if "zh" in (b.get("languages") or []) and fmts.get(_PG_EPUB):
            files.append({
                "label": "简体 AZW3", "ext": ".epub", "native": True,
                "url": fmts[_PG_EPUB], "simplified": True,
                "note": "取 EPUB → 正文转简体 → Calibre 排 AZW3，直接拷进设备就可读",
            })
        txt = fmts.get("text/plain; charset=utf-8")
        if txt:
            files.append({
                "label": "纯文本", "ext": ".txt", "native": True,
                "url": txt, "note": "无排版，但设备直接读；可随手转成笔记",
            })
        items.append({
            "id": f"pg:{b.get('id')}",
            "source": "gutenberg",
            "source_name": "古登堡",
            "title": (b.get("title") or "").strip() or "（无标题）",
            "author": _author_names(b.get("authors")),
            "langs": b.get("languages") or [],
            "downloads": b.get("download_count") or 0,
            "page_url": f"https://www.gutenberg.org/ebooks/{b.get('id')}",
            "cover": fmts.get("image/jpeg") or "",
            "files": files,
            "subjects": (b.get("subjects") or [])[:3],
        })
    return {"items": items, "count": raw.get("count") or 0}


def _classics(q: str, page: int) -> dict:
    """本地中文经典语料（chinese-poetry，MIT）。

    这是唯一一个不联网的书源：语料已经落在本地，检索和成书都是本地算的，
    所以没有线路超时的问题，也没有「源站改版」这回事。
    """
    if not classics_mod.available():
        return {"items": [], "count": 0}
    try:
        r = classics_mod.search(q=q, page=page, page_size=40)
    except Exception as ex:                       # noqa: BLE001
        raise FreeError(f"本地语料检索失败：{ex}") from ex

    items = []
    for b in r["items"]:
        works = b.get("works") or 0
        kinds = [s for s in (b.get("dynasty"), b.get("genre")) if s]
        items.append({
            "id": b["id"],
            "source": "classics",
            "source_name": "中文经典",
            "title": b["title"],
            "author": b.get("author") or "",
            "langs": ["zh"],
            "downloads": works,              # 没有下载量，用作品数当热度排序
            "page_url": "",                  # 本地语料，没有源站页面
            "cover": "",
            "files": [
                {
                    "label": "Kindle 原生 · 简体 AZW3", "ext": ".azw3", "native": True,
                    "url": f"classic:{b['id']}", "classic": True,
                    "note": "本地语料即时排成简体 AZW3，拷进设备即可读",
                },
                {
                    "label": "简体 EPUB", "ext": ".epub", "native": False,
                    "url": f"classic:{b['id']}", "classic": True,
                    "note": "生成简体 EPUB，给 KOReader 或写信发送",
                },
            ],
            "subjects": kinds,
        })
    return {"items": items, "count": r.get("total") or 0}


_LI_RE = re.compile(r'<li typeof="schema:Book" about="(/ebooks/[^"]+)">')
_NAME_RE = re.compile(r'<span property="schema:name">(.*?)</span>', re.S)
_IMG_RE = re.compile(r'<img src="(/images/covers/[^"]+)"')


def _standard_ebooks(q: str, page: int) -> dict:
    params = {"per-page": "24", "page": str(max(1, page))}
    if q:
        params["query"] = q
    elif page == 1:
        params["sort"] = "popularity"
    url = SE_LIST + "?" + "&".join(f"{k}={urllib.parse.quote(v)}" for k, v in params.items())
    doc = _get(url, timeout=SEARCH_TIMEOUT, tries=3).decode("utf-8", "ignore")

    items = []
    blocks = _LI_RE.split(doc)
    # split 后是 [前导, 路径1, 块1, 路径2, 块2, ...]
    for i in range(1, len(blocks) - 1, 2):
        path, block = blocks[i], blocks[i + 1]
        hits = _NAME_RE.findall(block)
        title = html.unescape(hits[0]).strip() if hits else ""
        author = html.unescape(hits[1]).strip() if len(hits) > 1 else ""
        if not title:
            continue
        segs = [s for s in path.split("/") if s]
        if len(segs) < 3:
            continue
        author_dir, slug = segs[-2], segs[-1]
        dl = f"{SE_BASE}/ebooks/{author_dir}/{slug}/downloads/{author_dir}_{slug}"
        cover = ""
        m = _IMG_RE.search(block)
        if m:
            cover = SE_BASE + m.group(1)
        items.append({
            "id": f"se:{author_dir}/{slug}",
            "source": "se",
            "source_name": "标准电子书",
            "title": title,
            "author": author or "佚名",
            "langs": ["en"],
            "downloads": 0,
            "page_url": SE_BASE + path,
            "cover": cover,
            "files": [
                {"label": "Kindle 原生 · AZW3", "ext": ".azw3", "native": True,
                 "url": f"{dl}.azw3?source=download",
                 "note": "精校排版，拷进 documents/ 即读，是这批书里最舒服的一版"},
                {"label": "EPUB", "ext": ".epub", "native": False,
                 "url": f"{dl}.epub?source=download",
                 "note": "Kindle 不认 EPUB，需走路线 A 转 AZW3 或路线 B 送信"},
            ],
            "subjects": [],
        })
    return {"items": items, "count": len(items)}


def _open_library(q: str, lang: str, page: int) -> dict:
    """Open Library —— 元数据与封面极佳的公有领域书目（含 Internet Archive 全文扫描）。

    只取 has_fulltext=true 的书，这样每条都带一个 Internet Archive 标识符（ia），
    能用 archive.org 的真文件做投递。封面走 covers.openlibrary.org 的稳定接口。
    注意：ia 下的具体文件名（.epub / .txt）按 Internet Archive 的通用命名约定拼接，
    下载管线会先验文件再落盘，拼错只会优雅报错、不会把错文件送进 Kindle。
    """
    if q:
        qry = q
    elif lang == "zh":
        qry = "古典文學"
    else:
        qry = "classic literature"
    params = {
        "q": qry,
        "page": str(max(1, page)),
        "limit": "24",
        "has_fulltext": "true",
        "fields": "title,author_name,cover_i,ia,key,edition_count,first_publish_year,language,has_fulltext",
    }
    if lang and _OL_LANG.get(lang):
        params["language"] = _OL_LANG[lang]
    url = OL_SEARCH + "?" + "&".join(
        f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    try:
        raw = json.loads(_get(url, timeout=SEARCH_TIMEOUT_FAST, tries=2).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as ex:
        raise FreeError("Open Library 返回的 JSON 无法解析") from ex

    items = []
    for b in raw.get("docs") or []:
        ia = b.get("ia") or []
        if isinstance(ia, str):
            ia = [ia]
        ia_id = ia[0] if ia else ""
        title = (b.get("title") or "").strip() or "（无标题）"
        authors = b.get("author_name") or []
        if isinstance(authors, str):
            authors = [authors]
        author = "、".join(a for a in authors[:3] if a) or "佚名"
        cover_i = b.get("cover_i")
        cover = f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else ""
        marc = b.get("language") or []
        langs = [_OL_LANG_SHOW.get(m, m) for m in marc if m][:3] or ["en"]
        key = (b.get("key") or "").strip()
        page_url = f"https://openlibrary.org{key}" if key else ""
        files = []
        if ia_id:
            files.append({
                "label": "EPUB（经 Internet Archive）", "ext": ".epub", "native": False,
                "url": f"https://archive.org/download/{ia_id}/{ia_id}.epub",
                "note": "取 IA 的 EPUB → 需走转换再送 Kindle；若链接失效可改用纯文本",
            })
            files.append({
                "label": "纯文本（经 Internet Archive）", "ext": ".txt", "native": True,
                "url": f"https://archive.org/download/{ia_id}/{ia_id}.txt",
                "note": "IA OCR 全文，设备直接读，最稳",
            })
        items.append({
            "id": f"ol:{key}" if key else f"ol:{ia_id}",
            "source": "openlibrary",
            "source_name": "Open Library",
            "title": title,
            "author": author,
            "langs": langs,
            "downloads": b.get("edition_count") or 0,
            "page_url": page_url,
            "cover": cover,
            "files": files,
            "subjects": [],
        })
    return {"items": items, "count": raw.get("numFound") or raw.get("num_found") or 0}


def _wikisource(q: str, lang: str, page: int) -> dict:
    """维基文库 Wikisource —— 志愿者逐字校对的公有领域全文，可直接导出 EPUB。

    检索走 MediaWiki API（srnamespace=0 只取正文命名空间）；EPUB 走 Wikimedia 官方
    导出工具 ws-export（/?format=epub&page=<标题>），返回结构合法的 EPUB。
    中文书切到 zh.wikisource.org，其余走 en.wikisource.org。
    """
    sub = _WS_SUB.get(lang, "en")
    limit = 20
    off = (max(1, page) - 1) * limit
    if q:
        srsearch = q
    elif lang == "zh":
        srsearch = "古典文學"
    else:
        srsearch = "classic literature"
    params = {
        "action": "query", "list": "search", "format": "json",
        "srnamespace": "0", "srlimit": str(limit), "sroffset": str(off),
        "srinfo": "totalhits", "srsearch": srsearch,
    }
    url = WS_API.format(sub=sub) + "?" + "&".join(
        f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    try:
        raw = json.loads(_get(url, timeout=SEARCH_TIMEOUT_FAST, tries=2).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as ex:
        raise FreeError("维基文库返回的 JSON 无法解析") from ex

    qry = raw.get("query") or {}
    hits = qry.get("search") or []
    total = (qry.get("searchinfo") or {}).get("totalhits") or 0
    base = f"https://{sub}.wikisource.org"
    items = []
    for b in hits:
        title = (b.get("title") or "").strip()
        if not title:
            continue
        page_name = title.replace(" ", "_")
        pageid = b.get("pageid")
        pid = f"ws:{sub}:{pageid}" if pageid else f"ws:{sub}:{page_name}"
        items.append({
            "id": pid,
            "source": "wikisource",
            "source_name": "维基文库",
            "title": title,
            "author": "",
            "langs": [sub],
            "downloads": 0,
            "page_url": f"{base}/wiki/{urllib.parse.quote(title)}",
            "cover": "",
            "files": [
                {
                    "label": "EPUB（Wikimedia 官方导出）", "ext": ".epub", "native": False,
                    "url": f"{WS_EXPORT}?format=epub&page={urllib.parse.quote(page_name)}",
                    "note": "维基文库公版全文 → 官方工具导出 EPUB，需转换后送 Kindle",
                },
            ],
            "subjects": [],
        })
    return {"items": items, "count": total}


def search(q: str = "", source: str = "all", lang: str = "", page: int = 1) -> dict:
    """跨源检索。任一源挂了不影响另一个源出结果。"""
    q = (q or "").strip()
    page = max(1, int(page or 1))
    key = (q, source, lang, page)
    with _SEARCH_LOCK:
        hit = _SEARCH_CACHE.get(key)
        if hit and time.time() - hit[0] < SEARCH_TTL:
            return hit[1]

    items: list[dict] = []
    errors: list[str] = []
    total = 0

    # 各源各跑各的线程：总耗时取决于慢的那个，而不是两者相加。
    want_pg = source in ("all", "gutenberg")
    want_se = source in ("all", "se") and (not lang or lang == "en")
    # 中文经典是本地语料，只在中文语境下参与；英文检索时不掺和
    want_cl = source in ("all", "classics") and (not lang or lang == "zh")
    want_ol = source in ("all", "openlibrary")
    want_ws = source in ("all", "wikisource")
    results: dict[str, dict] = {}
    boom: dict[str, str] = {}

    def run(name: str, fn) -> None:
        try:
            results[name] = fn()
        except FreeError as ex:
            boom[name] = str(ex)

    threads = []
    if want_pg:
        threads.append(("古登堡", threading.Thread(
            target=run, args=("古登堡", lambda: _gutenberg(q, lang, page)), daemon=True)))
    if want_se:
        threads.append(("标准电子书", threading.Thread(
            target=run, args=("标准电子书", lambda: _standard_ebooks(q, page)), daemon=True)))
    if want_ol:
        threads.append(("Open Library", threading.Thread(
            target=run, args=("Open Library", lambda: _open_library(q, lang, page)), daemon=True)))
    if want_ws:
        threads.append(("维基文库", threading.Thread(
            target=run, args=("维基文库", lambda: _wikisource(q, lang, page)), daemon=True)))
    if want_cl:
        threads.append(("中文经典", threading.Thread(
            target=run, args=("中文经典", lambda: _classics(q, page)), daemon=True)))
    for _, t in threads:
        t.start()
    # 整体预算：所有源共享 SEARCH_DEADLINE，而不是每个源各等这么久。
    # 顺序 join 会让耗时线性叠加，慢源一多就整体超时；改成「全局倒计时」，
    # 到点（默认 25s）不论还有几个源没答上来都先收尾，给出已到的结果。
    deadline = time.time() + SEARCH_DEADLINE
    for _, t in threads:
        t.join(max(0.0, deadline - time.time()))

    # 到点了还没答上来的源就放弃 —— 宁可先给一半结果，也不要让页面干等
    for name, t in threads:
        if t.is_alive():
            boom[name] = "这次没答上来（跨境线路被占满时常见），等一下重新检索即可"

    for name, r in results.items():
        got = r["items"]
        # 本地语料有上万条，混合检索时不限量的话会把古登堡全挤下去
        if name == "中文经典" and source == "all":
            got = got[:12]
        items += got
        total += r["count"]
    errors = [f"{k}：{v}" for k, v in boom.items()]
    partial = any(t.is_alive() for _, t in threads)

    # 古登堡热度靠前；标准电子书排版更好 —— 精选版排在前面，同源内按热度
    items.sort(key=lambda x: (0 if x["source"] == "se" else 1, -x["downloads"]))

    data = {"items": items[:40], "count": total, "page": page, "query": q,
            "source": source, "lang": lang, "errors": errors,
            "partial": partial, "stale": False, "hint": _hint(q, lang, len(items))}

    if partial:
        # 半成品不进缓存，否则用户点「重试」会立刻拿到同一份残缺结果
        data["hint"] = ("线路被占满（比如正在下载大文件），只取回了部分书源的结果。"
                        "稍等片刻再点一次「检索」，缺的那半就会补上。")
        return data

    if not items and errors:
        cached = _disk_read(_disk_key(q, source, lang, page))
        if cached:
            cached = dict(cached)
            cached["stale"] = True
            cached["errors"] = errors
            cached["hint"] = "源站这会儿连不上，下面是上次取回的结果（仍可正常下载）。"
            return cached

    with _SEARCH_LOCK:
        _SEARCH_CACHE[key] = (time.time(), data)
        if len(_SEARCH_CACHE) > 60:
            for k in list(_SEARCH_CACHE)[:20]:
                _SEARCH_CACHE.pop(k, None)
    _disk_write(_disk_key(q, source, lang, page), data)
    return data


def _hint(q: str, lang: str, n: int) -> str:
    if q and not n and re.search(r"[\u4e00-\u9fff]", q):
        return ("没有命中。古登堡的中文书名大多存的是繁体，试试用繁体（如 紅樓夢）检索，"
                "或把「语言」切到中文、直接浏览中文公版书排行榜。")
    if q and not n:
        return "没有命中。换个更短的关键词试试，比如只填作者姓氏或书名里的一个词。"
    if lang == "zh" and not q:
        return "这是按下载量排序的中文公版书榜；古登堡共收录 444 册中文书，翻页可继续看。"
    return ""


# ---------------------------------------------------------------- 下载

_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_ORDER: list[str] = []
_STOP: set[str] = set()
_WORKER: threading.Thread | None = None
_SEQ = 0


def _now() -> str:
    return time.strftime("%H:%M:%S")


def _unique_name(dest_dir: str, stem: str, ext: str) -> str:
    cand = os.path.join(dest_dir, f"{stem}{ext}")
    n = 2
    while os.path.exists(cand):
        cand = os.path.join(dest_dir, f"{stem} ({n}){ext}")
        n += 1
    return cand


def _readable_name(title: str, author: str, ext: str) -> str:
    t = epub_mod.safe_filename(title, 60) or "未命名"
    a = epub_mod.safe_filename(author, 30)
    stem = f"{t} - {a}" if a and a != "佚名" else t
    return stem + ext


def _open(url: str, start: int | None = None, end: int | None = None, timeout: float = READ_TIMEOUT):
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if start is not None:
        headers["Range"] = f"bytes={start}-{end}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)


def _probe(url: str, tries: int = 3) -> tuple[int, bool]:
    """返回 (总体积, 是否支持 Range)。体积未知时给 0。"""
    last: FreeError | None = None
    for attempt in range(tries):
        if attempt:
            time.sleep(1.5 * attempt)
        try:
            with _open(url, 0, 0, timeout=PROBE_TIMEOUT) as f:
                cr = f.headers.get("Content-Range") or ""
                total = int(cr.split("/")[-1]) if "/" in cr and cr.split("/")[-1].isdigit() else 0
                if f.status == 206:
                    return total, True
                return int(f.headers.get("Content-Length") or 0), False
        except urllib.error.HTTPError as ex:
            if ex.code in (404, 410):
                raise FreeError("这个格式在源站已经下架了，换一个格式试试") from ex
            last = FreeError(f"源站返回 HTTP {ex.code}")
        except urllib.error.URLError as ex:
            last = FreeError(f"连不上源站：{ex.reason}")
        except TimeoutError:
            last = FreeError("探测超时，跨境线路这会儿不太稳")
    raise last or FreeError("源站探测失败")


def _plan(total: int, n: int) -> list[tuple[int, int]]:
    step = total // n
    out = []
    for i in range(n):
        s = i * step
        e = total - 1 if i == n - 1 else (i + 1) * step - 1
        out.append((s, e))
    return out


def _fetch_segment(job_id: str, url: str, path: str, start: int, end: int,
                   on_bytes, counter: dict, tries: int = 4) -> None:
    """下载一个分片。中断了就带着已下的字节重开 Range —— 这就是断点续传。"""
    want = end - start + 1
    have = os.path.getsize(path) if os.path.isfile(path) else 0
    if have >= want:                           # 上一次已经下完了
        counter["done"] += want
        return

    last: Exception | None = None
    for attempt in range(tries):
        if job_id in _STOP:
            return
        have = os.path.getsize(path) if os.path.isfile(path) else 0
        if have >= want:
            return
        try:
            with _open(url, start + have, end) as f:
                with open(path, "ab") as out:
                    while True:
                        if job_id in _STOP:
                            return
                        chunk = f.read(CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        on_bytes(len(chunk), counter)
            if (os.path.getsize(path) if os.path.isfile(path) else 0) >= want:
                return
        except (urllib.error.URLError, TimeoutError, OSError) as ex:
            last = ex                                       # 带着进度重试，不从头再来
        if attempt < tries - 1:
            time.sleep(1.0 * (attempt + 1))
    raise FreeError(f"分片重试 {tries} 次仍未取完：{last}")


def _verify(tmp: str, ext: str) -> str:
    """下载完的第一件事是验货，别把一张 HTML 错误页当成书送进 Kindle。"""
    ext = ext.lower()
    if ext in (".mobi", ".azw", ".azw3", ".prc"):
        kind = mobi_mod.sniff(tmp)
        if kind not in ("mobi", "kfx"):
            raise FreeError("取回的文件不是 MOBI/AZW3（源站可能返回了错误页）")
        size = os.path.getsize(tmp)
        if size < 8192:
            raise FreeError("文件体积异常偏小，可能没有取全")
        return f"{kind.upper()} 结构正常，{size // 1024} KB"
    if ext == ".epub":
        if not zipfile.is_zipfile(tmp):
            raise FreeError("取回的文件不是 EPUB（源站可能返回了错误页）")
        with zipfile.ZipFile(tmp) as z:
            names = z.namelist()
            if "META-INF/container.xml" not in names:
                raise FreeError("EPUB 结构不完整，缺 META-INF/container.xml")
            if names and names[0] != "mimetype":
                raise FreeError("EPUB 的 mimetype 不在首位，投递前需先整理")
        return f"EPUB 结构正常，{os.path.getsize(tmp) // 1024} KB"
    return f"{os.path.getsize(tmp) // 1024} KB"


def _run_job(job: dict) -> None:
    url, ext = job["url"], job["ext"]
    tmp_dir = os.path.join(CACHE_DIR, job["id"])
    os.makedirs(tmp_dir, exist_ok=True)
    final = os.path.join(tmp_dir, "payload" + ext)
    t0 = time.time()
    last = {"t": time.time(), "b": 0}

    def on_bytes(n: int, counter: dict) -> None:
        counter["got"] += n
        now = time.time()
        if now - last["t"] >= 0.6:
            inst = (counter["got"] - last["b"]) / max(now - last["t"], 0.001)
            job["speed"] = inst
            job["speed_avg"] = counter["got"] / max(now - t0, 0.001)
            last["t"], last["b"] = now, counter["got"]
            job["got"] = counter["got"]
            if job["total"]:
                job["percent"] = min(99, int(counter["got"] * 100 / job["total"]))
            sp = job["speed_avg"] or inst
            if job["total"] and sp > 0:
                job["eta"] = max(0, int((job["total"] - counter["got"]) / sp))

    try:
        job.update({"status": "探测中", "started": _now()})
        total, ranged = _probe(url)
        if total > MAX_BYTES:
            raise FreeError(f"体积 {total // 1048576} MB 超出上限")
        job["total"] = total
        job["status"] = "下载中"
        job["ranged"] = ranged

        counter = {"got": 0, "done": 0}
        if ranged and total >= SEGMENT_MIN:
            parts = _plan(total, SEGMENTS)
            paths = [os.path.join(tmp_dir, f"part{i}") for i in range(len(parts))]
            existing = sum(os.path.getsize(p) for p in paths if os.path.isfile(p))
            counter["got"] = counter["done"] = existing
            threads = []
            for i, (s, e) in enumerate(parts):
                th = threading.Thread(target=_fetch_segment,
                                      args=(job["id"], url, paths[i], s, e, on_bytes, counter),
                                      daemon=True)
                th.start()
                threads.append(th)
            for th in threads:
                th.join()
            if job["id"] in _STOP:
                raise FreeError("已取消")
            with open(final, "wb") as out:
                for p in paths:
                    if os.path.isfile(p):
                        with open(p, "rb") as src:
                            shutil.copyfileobj(src, out, CHUNK)
        else:
            job["segments"] = 1
            last_ex: Exception | None = None
            for attempt in range(3):
                counter["got"] = 0            # 单流是整段重来，计数也要归零
                job["got"] = 0
                try:
                    with _open(url) as f, open(final, "wb") as out:
                        while True:
                            if job["id"] in _STOP:
                                raise FreeError("已取消")
                            chunk = f.read(CHUNK)
                            if not chunk:
                                break
                            out.write(chunk)
                            on_bytes(len(chunk), counter)
                    break
                except FreeError:
                    raise
                except (urllib.error.URLError, TimeoutError, OSError) as ex:
                    last_ex = ex
                    time.sleep(1.5 * (attempt + 1))
            if last_ex is not None and not os.path.isfile(final):
                raise FreeError(f"下载失败：{last_ex}")

        job["status"] = "校验中"
        job["got"] = os.path.getsize(final) if os.path.isfile(final) else 0
        if job["total"] and job["got"] < job["total"]:
            raise FreeError(f"只取到 {job['got'] // 1024} KB / {job['total'] // 1024} KB，网络中断了")

        note = _verify(final, ext)

        os.makedirs(INBOX_DIR, exist_ok=True)
        dest = _unique_name(INBOX_DIR, os.path.splitext(
            _readable_name(job["title"], job["author"], ext))[0], ext)
        try:
            shutil.move(final, dest)
        except OSError:
            shutil.copy2(final, dest)
            os.remove(final)

        # 中文书默认是繁体，要求简体的话在这里转成简体 AZW3。
        # 原文 EPUB 保留在「收书」里 —— 繁体原貌也是一份有价值的版本，不替用户删。
        if job.get("simplified") and ext == ".epub":
            job["status"] = "转简体"
            from . import deliver as deliv_mod
            steps = deliv_mod.to_simplified_azw3(
                [dest], INBOX_DIR, tmp_dir, find_ebook_convert())
            st = steps[0]
            if not st.ok:
                raise FreeError(st.message)
            dest = st.out
            note = st.message + "；原文（繁体）也留在「收书」里"

        job.update({"status": "完成", "percent": 100, "out": dest,
                    "out_name": os.path.basename(dest), "note": note,
                    "elapsed": round(time.time() - t0, 1)})

        if job.get("push"):
            from . import deliver as deliv_mod
            from . import device as dev_mod
            dev = dev_mod.find_kindle()
            steps = deliv_mod.push_native(
                [dest], dev.documents if dev else "",
                os.path.join(BASE_DIR, "导出", "Kindle书"))
            job["pushed"] = [s.to_dict() for s in steps]

    except FreeError as ex:
        msg = str(ex)
        job.update({"status": "已取消" if msg == "已取消" else "失败", "error": msg})
        _maybe_auto_retry(job, _is_transient(msg))
    except (OSError, urllib.error.URLError, TimeoutError) as ex:
        job.update({"status": "失败", "error": f"网络或磁盘出错：{ex}"})
        _maybe_auto_retry(job, True)
    except Exception as ex:                                    # 兜底，别让线程静静死掉
        job.update({"status": "失败", "error": f"意外错误：{ex}"})
    finally:
        _STOP.discard(job["id"])
        # 失败/取消时保留分片目录 —— 重试时从断点继续，不必从零开始
        if job["status"] == "完成":
            shutil.rmtree(tmp_dir, ignore_errors=True)


# 这些字样的错误是线路抖动，值得自动再试一次；校验类错误（比如取回的不是书）重试也没用
_TRANSIENT_MARKS = ("网络中断了", "分片重试", "下载失败", "连不上", "超时")


def _is_transient(msg: str) -> bool:
    return any(m in msg for m in _TRANSIENT_MARKS)


def _maybe_auto_retry(job: dict, transient: bool) -> None:
    """网络类失败自动再排一次队（最多一次），已下载的分片留着续用。"""
    if not transient or job.get("auto_done") or job["status"] != "失败":
        return
    job["auto_done"] = True
    job["status"] = "自动重试排队"
    job["error"] = (job.get("error") or "") + "（线路抖动，8 秒后自动重试）"

    def go() -> None:
        with _JOB_LOCK:
            j = _JOBS.get(job["id"])
            if not j or j["status"] != "自动重试排队":   # 期间被手动重试/清空就不折腾了
                return
            j["status"] = "排队"
            j["queued"] = _now()
        _ensure_worker()

    threading.Timer(8.0, go).start()


def _worker() -> None:
    while True:
        job = None
        with _JOB_LOCK:
            for jid in _ORDER:
                cand = _JOBS.get(jid)
                if cand and cand["status"] == "排队":
                    cand["status"] = "等待中"
                    job = cand
                    break
        if job is None:
            return
        _run_job(job)


def _ensure_worker() -> None:
    global _WORKER
    if _WORKER and _WORKER.is_alive():
        return
    _WORKER = threading.Thread(target=_worker, daemon=True)
    _WORKER.start()


def enqueue(items: list[dict], push: bool = False) -> dict:
    if not items:
        raise FreeError("没有选中任何书")
    if len(items) > 12:
        raise FreeError("一次最多取 12 本，太多了线路扛不住")
    global _SEQ
    made = []
    with _JOB_LOCK:
        for it in items:
            url = (it.get("url") or "").strip()
            ext = (it.get("ext") or "").lower()
            if not url.startswith("https://") or ext not in (".mobi", ".azw", ".azw3", ".epub", ".txt"):
                continue
            _SEQ += 1
            jid = f"{int(time.time())}-{_SEQ}"
            _JOBS[jid] = {
                "id": jid, "title": (it.get("title") or "").strip() or "未命名",
                "author": (it.get("author") or "").strip(),
                "source_name": it.get("source_name") or "",
                "url": url, "ext": ext, "push": bool(push),
                "simplified": bool(it.get("simplified")),
                "status": "排队", "got": 0, "total": 0, "percent": 0,
                "speed": 0.0, "speed_avg": 0.0, "eta": 0, "error": "",
                "out": "", "queued": _now(),
            }
            _ORDER.append(jid)
            made.append(jid)
    if not made:
        raise FreeError("没有可下载的链接")
    _ensure_worker()
    return {"ok": True, "ids": made, "queued": len(made)}


def cancel(job_id: str = "") -> dict:
    with _JOB_LOCK:
        if job_id:
            if job_id in _JOBS and _JOBS[job_id]["status"] not in ("完成", "失败", "已取消"):
                _STOP.add(job_id)
                return {"ok": True, "id": job_id}
            return {"ok": False, "error": "这个任务已经结束了"}
        ids = [j for j in _ORDER if _JOBS.get(j) and
               _JOBS[j]["status"] not in ("完成", "失败", "已取消")]
        _STOP.update(ids)
    return {"ok": True, "cancelled": ids}


def retry(job_id: str = "") -> dict:
    """手动重试：带 id 重试单个任务；不带 id 重试全部失败的。分片在，从断点继续。"""
    done: list[str] = []
    with _JOB_LOCK:
        if job_id:
            targets = [job_id]
        else:
            targets = [j for j in _ORDER if _JOBS.get(j) and
                       _JOBS[j]["status"] in ("失败", "已取消", "自动重试排队")]
        for jid in targets:
            j = _JOBS.get(jid)
            if not j or j["status"] not in ("失败", "已取消", "自动重试排队"):
                continue
            j["status"] = "排队"
            j["error"] = ""
            j["percent"] = 0
            j["queued"] = _now()
            done.append(jid)
    if not done:
        return {"ok": False, "error": "没有可重试的失败任务"}
    _ensure_worker()
    return {"ok": True, "retried": done}


def clear_finished() -> dict:
    with _JOB_LOCK:
        for jid in [j for j in _ORDER if _JOBS.get(j) and
                    _JOBS[j]["status"] in ("完成", "失败", "已取消")]:
            _ORDER.remove(jid)
            _JOBS.pop(jid, None)
            shutil.rmtree(os.path.join(CACHE_DIR, jid), ignore_errors=True)
    return {"ok": True}


def state() -> dict:
    with _JOB_LOCK:
        jobs = [dict(_JOBS[j]) for j in _ORDER if j in _JOBS]
    active = [j for j in jobs if j["status"] in
              ("排队", "等待中", "探测中", "下载中", "校验中", "自动重试排队")]
    cur = next((j for j in active if j["status"] in ("探测中", "下载中", "校验中")), None)
    ok = len([j for j in jobs if j["status"] == "完成"])
    return {
        "jobs": jobs[-30:],
        "active": len(active),
        "current": cur,
        "done": ok,
        "failed": len([j for j in jobs if j["status"] == "失败"]),
        "inbox": INBOX_DIR,
        "busy": bool(active),
    }
