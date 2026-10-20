# -*- coding: utf-8 -*-
"""中文经典文库 —— 把 chinese-poetry（MIT 授权）的语料变成能送进 Kindle 的书。

数据源是纯文本 JSON，分两种形态：
  · 成册的书：``论语`` ``大学`` ``诗经`` ``唐诗三百首`` 等，一个文件就是一本书；
  · 作品总集：``全唐诗`` ``宋词`` ``元曲``，一个文件是几百位作者的一大堆作品，
    按作者拆开才是「书」—— 一本《李白集》比一个 5.5 万首的大杂烩有用得多。

所以本模块做两件事：建索引（含按作者的作品统计），以及把索引条目渲染成 EPUB。
正文繁简混存（全唐诗是繁体，论语、诗经是简体），转简体交给 hanzi 模块，
它自己会判断该不该转。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

from . import epub as epub_mod
from . import hanzi
from . import paths as _paths

BASE_DIR = _paths.data_dir()
CORPUS_DIR = os.path.join(BASE_DIR, "corpus", "chinese-poetry")
CACHE_DIR = os.path.join(BASE_DIR, "工具", "缓存")
INDEX_FILE = os.path.join(CACHE_DIR, "经典索引.json")

LICENSE_NOTE = "MIT"

# 成册的书：文件名 → (书名, 作者/编者, 朝代)。
# 语料库的文件名多半是拼音，不映射的话书库里会显示 "lunyu"。
WHOLE_BOOKS: dict[str, tuple[str, str, str]] = {
    "论语/lunyu.json": ("论语", "孔子及其弟子", "先秦"),
    "四书五经/daxue.json": ("大学", "曾参", "先秦"),
    "四书五经/zhongyong.json": ("中庸", "子思", "先秦"),
    "四书五经/mengzi.json": ("孟子", "孟轲", "先秦"),
    "诗经/shijing.json": ("诗经", "佚名", "先秦"),
    "楚辞/chuci.json": ("楚辞", "屈原等", "先秦"),
    "蒙学/sanzijing-new.json": ("三字经", "王应麟", "宋"),
    "蒙学/sanzijing-traditional.json": ("三字经（繁体原本）", "王应麟", "宋"),
    "蒙学/baijiaxing.json": ("百家姓", "佚名", "宋"),
    "蒙学/qianziwen.json": ("千字文", "周兴嗣", "南北朝"),
    "蒙学/dizigui.json": ("弟子规", "李毓秀", "清"),
    "蒙学/qianjiashi.json": ("千家诗", "谢枋得等", "宋"),
    "蒙学/shenglvqimeng.json": ("声律启蒙", "车万育", "清"),
    "蒙学/tangshisanbaishou.json": ("唐诗三百首", "蘅塘退士", "清"),
    "蒙学/guwenguanzhi.json": ("古文观止", "吴楚材、吴调侯", "清"),
    "蒙学/youxueqionglin.json": ("幼学琼林", "丘濬", "明"),
    "蒙学/zengguangxianwen.json": ("增广贤文", "佚名", "明"),
    "蒙学/zhuzijiaxun.json": ("朱子家训", "朱熹", "宋"),
    "蒙学/wenzimengqiu.json": ("文字蒙求", "王筠", "清"),
    "幽梦影/youmengying.json": ("幽梦影", "张潮", "清"),
    "水墨唐诗/shuimotangshi.json": ("水墨唐诗", "佚名", "唐"),
    "纳兰性德/纳兰性德诗集.json": ("纳兰性德全集", "纳兰性德", "清"),
    "曹操诗集/caocao.json": ("曹操诗集", "曹操", "三国"),
}

# 一个目录里的多个文件合起来才是一本书（分卷、分卷类的书）。
# 目录前缀 → (书名, 作者/编者, 朝代)
MERGED_BOOKS: dict[str, tuple[str, str, str]] = {
    "五代诗词/huajianji": ("花间集", "赵崇祚", "五代"),
    "五代诗词/nantang": ("南唐二主词", "李煜等", "五代"),
}

# 作品总集：目录 → (朝代, 体裁)。按作者拆书。
COLLECTIONS: dict[str, tuple[str, str]] = {
    "全唐诗": ("唐", "诗"),
    "宋词": ("宋", "词"),
    "元曲": ("元", "曲"),
    "御定全唐詩": ("唐", "诗"),
}

# 总集里要跳过的非正文文件（作者表、说明等）
_SKIP_NAMES = {"authors.tang.json", "authors.song.json", "README.md",
               "authors.json", "intro.json"}

_INDEX_LOCK = threading.Lock()
_INDEX: dict | None = None

_WS = re.compile(r"\s+")


# ------------------------------------------------------------------ 索引


def available() -> bool:
    """语料在不在。没下过就是 False，前端据此提示。"""
    return os.path.isdir(CORPUS_DIR) and any(
        f.endswith(".json") for _, _, fs in os.walk(CORPUS_DIR) for f in fs
    )


def status() -> dict:
    """语料与索引的现状，给前端显示「还没下载 / 正在建索引 / 有 N 本书」。"""
    have = available()
    cached = _load_cache() or {}
    return {
        "ready": have,
        "corpus": CORPUS_DIR,
        "indexed": bool(cached.get("books")),
        "total": cached.get("total") or 0,
        "built": cached.get("built") or 0,
        "elapsed": cached.get("elapsed") or 0,
        "license": LICENSE_NOTE,
        "source": "chinese-poetry/chinese-poetry",
    }


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _items_of(data) -> list[tuple[str, list[str], str]]:
    """把各种 JSON 形态统一成 [(篇名, 段落列表, 作者)]。

    语料的字段和层级都不统一，这里是实地踩出来的几种：
      · 正文可能在 ``paragraphs``（全唐诗、元曲）、``para``（纳兰性德）、
        ``content``（幽梦影是字符串、楚辞是字符串数组、蒙学是嵌套数组）；
      · 标题可能在 ``title``、``rhythmic``（词牌）或 ``chapter`` 里，也可能压根没有；
      · 唐诗三百首这类是两层嵌套（体裁 → 篇目），不递归展开就一篇都读不到。
    """
    out: list[tuple[str, list[str], str]] = []
    _walk(data, out, "", "")
    return out


def _walk(node, out: list, prefix: str, dauthor: str) -> None:
    if isinstance(node, list):
        for it in node:
            _walk(it, out, prefix, dauthor)
        return
    if not isinstance(node, dict):
        return

    author = str(node.get("author") or "").strip() or dauthor
    # 有些 author 字段塞的是作者简介（文字蒙求就有两百字），截断免得书名被撑爆
    if len(author) > 24:
        author = author[:24].rstrip("，,。;； ") + "…"

    # 1) 明文正文
    paras = node.get("paragraphs") or node.get("para")
    if isinstance(paras, str):
        paras = [paras]
    if paras:
        paras = [p for p in paras if isinstance(p, str) and p.strip()]
        if paras:
            out.append((_title_of(node, prefix, paras), paras, author))
            return

    content = node.get("content")

    # 2) content 是字符串数组 —— 楚辞、诗经的正文
    if isinstance(content, list) and content and all(isinstance(x, str) for x in content):
        paras = [p for p in content if p.strip()]
        if paras:
            out.append((_title_of(node, prefix, paras), paras, author))
            return

    # 3) content 是字符串 —— 幽梦影这类一条一则
    if isinstance(content, str) and content.strip():
        out.append((_title_of(node, prefix, [content]), [content.strip()], author))
        return

    # 4) content 是嵌套数组 —— 蒙学的「体裁 → 篇目」，往下钻一层
    if isinstance(content, list):
        # 只有「体裁」或「卷名」才配进篇名前缀；纯 title 那是书名本身，
        # 加进去会让每章都顶着「唐诗三百首 · 五言绝句 · 静夜思」这种累赘标题
        if node.get("type"):
            sub = str(node["type"]).strip()
        elif node.get("chapter") and not node.get("title"):
            sub = str(node["chapter"]).strip()
        else:
            sub = ""
        next_prefix = f"{prefix} · {sub}" if prefix and sub else (sub or prefix)
        _walk(content, out, next_prefix, author)


def _title_of(node: dict, prefix: str, paras: list[str]) -> str:
    title = str(node.get("title") or node.get("rhythmic") or node.get("chapter") or "").strip()
    # 诗经、楚辞有「国风 / 周南」两级，拼进去才不至于几十章同名
    sec = node.get("section")
    if isinstance(sec, str) and sec and sec != title and node.get("chapter"):
        title = f"{node['chapter']}·{sec} · {title}".strip(" ·")
    if not title:
        head = _WS.sub(" ", paras[0]).strip()
        title = head[:14] + ("…" if len(head) > 14 else "")
    return f"{prefix} · {title}" if prefix and title else (title or prefix or "正文")


def _dynasty_of(rel: str, fallback: str) -> str:
    """从文件名推断朝代。

    「全唐诗」这个目录名是骗人的 —— 它里面 ``poet.tang.*`` 是唐诗 5.5 万首，
    ``poet.song.*`` 是宋诗 26 万首。按目录标朝代会把陆游、杨万里全标成唐朝。
    """
    base = os.path.basename(rel).lower()
    if ".song." in base:
        return "宋"
    if ".tang." in base:
        return "唐"
    if "yuanqu" in base:
        return "元"
    return fallback


def _merged_prefix(rel: str) -> str:
    for prefix in MERGED_BOOKS:
        if rel.startswith(prefix + "/"):
            return prefix
    return ""


def _json_files() -> list[str]:
    """语料库里所有 JSON 的相对路径，按目录排序保证顺序稳定。"""
    out = []
    for root, _, files in os.walk(CORPUS_DIR):
        for f in files:
            if not f.endswith(".json"):
                continue
            rel = os.path.relpath(os.path.join(root, f), CORPUS_DIR).replace("\\", "/")
            out.append(rel)
    out.sort()
    return out


def build_index(force: bool = False) -> dict:
    """扫描语料建书目。结果落盘缓存，第二次起直接读。

    总集要按作者聚合，必须把全唐诗那 141 MB 读一遍，所以第一次会慢几十秒。
    缓存因此是必要的，不是优化。
    """
    global _INDEX
    with _INDEX_LOCK:
        if _INDEX is not None and not force:
            return _INDEX
        if not force:
            cached = _load_cache()
            if cached:
                _INDEX = cached
                return _INDEX

        t0 = time.time()
        books: list[dict] = []
        by_author: dict[str, dict] = {}
        merged: dict[str, dict] = {}

        for rel in _json_files():
            top = rel.split("/", 1)[0]
            base = os.path.basename(rel)

            if base in _SKIP_NAMES:
                continue

            # 分卷的书：一个目录合起来才是一本
            prefix = _merged_prefix(rel)
            if prefix:
                title, author, dynasty = MERGED_BOOKS[prefix]
                ent = merged.get(prefix)
                if ent is None:
                    ent = merged[prefix] = {
                        "id": "merged:" + prefix,
                        "title": title, "author": author, "dynasty": dynasty,
                        "kind": "merged", "works": 0, "paras": 0,
                        "files": [], "license": LICENSE_NOTE,
                    }
                for _, paras, _ in _items_of(_read(os.path.join(CORPUS_DIR, rel))):
                    ent["works"] += 1
                    ent["paras"] += len(paras)
                ent["files"].append(rel)     # 已按路径排序，卷序自然是对的
                continue

            if rel in WHOLE_BOOKS:
                title, author, dynasty = WHOLE_BOOKS[rel]
                data = _read(os.path.join(CORPUS_DIR, rel))
                items = _items_of(data)
                books.append({
                    "id": "book:" + rel,
                    "title": title, "author": author, "dynasty": dynasty,
                    "kind": "book", "works": len(items),
                    "paras": sum(len(p) for _, p, _ in items),
                    "files": [rel], "license": LICENSE_NOTE,
                })
                continue

            if top in COLLECTIONS and base not in _SKIP_NAMES:
                dynasty, genre = COLLECTIONS[top]
                dynasty = _dynasty_of(rel, dynasty)
                data = _read(os.path.join(CORPUS_DIR, rel))
                for title, paras, author in _items_of(data):
                    if not author:
                        continue
                    # 语料本身简繁混存：宋词里写「陆游」，全唐诗里写「陸游」。
                    # 不统一的话同一个人会变成两位作者、两本集子。
                    author = hanzi.to_simplified(author)
                    # 同一位作者会出现在多个目录里（李白既在「全唐诗」也在
                    # 「御定全唐詩」），按 体裁+朝代+作者 归成一本，否则书库里
                    # 会有两本同名的《李白诗集》。诗和词分开，免得陆游的词混进诗集。
                    key = f"{genre}|{dynasty}|{author}"
                    ent = by_author.get(key)
                    if ent is None:
                        ent = by_author[key] = {
                            "id": "author:" + key,
                            "title": f"{author}{genre}集",
                            "author": author, "dynasty": dynasty,
                            "genre": genre, "kind": "author",
                            "works": 0, "paras": 0, "files": [],
                            "license": LICENSE_NOTE,
                        }
                    ent["works"] += 1
                    ent["paras"] += len(paras)
                    if rel not in ent["files"]:
                        ent["files"].append(rel)
                continue

        books.extend(merged.values())
        books.extend(by_author.values())

        # 只有当同一位作者横跨多个朝代（李白在唐在宋都有）时才标朝代，
        # 否则分不清是哪一本。单纯「有诗集也有词集」不算，体裁已经写在标题里了。
        dyns: dict[str, set[str]] = {}
        for b in books:
            if b["kind"] == "author":
                dyns.setdefault(b["author"], set()).add(b["dynasty"])
        for b in books:
            if b["kind"] == "author" and len(dyns.get(b["author"]) or ()) > 1:
                b["title"] = f"{b['author']}（{b['dynasty']}）{b['genre']}集"

        # 成册的书排最前：不这么做的话，首页会被「陸游诗集 9277 首」这类
        # 大部头占满，而用户想找的《论语》《诗经》要翻二十页才看得到。
        _ORDER = {"book": 0, "merged": 1, "author": 2}
        books.sort(key=lambda b: (_ORDER.get(b["kind"], 3), -b["works"], b["title"]))

        _INDEX = {
            "built": time.time(),
            "elapsed": round(time.time() - t0, 1),
            "corpus": CORPUS_DIR,
            "license": LICENSE_NOTE,
            "total": len(books),
            "books": books,
        }
        _save_cache(_INDEX)
        return _INDEX


def _load_cache() -> dict | None:
    try:
        with open(INDEX_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not d.get("books"):
        return None
    return d


def _save_cache(d: dict) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = INDEX_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, INDEX_FILE)
    except OSError:
        pass


# ------------------------------------------------------------------ 检索


def search(q: str = "", page: int = 1, page_size: int = 40) -> dict:
    """书名 / 作者模糊检索。空 query 按作品数从多到少给。"""
    idx = build_index()
    books = idx["books"]
    qs = (q or "").strip()

    if qs:
        # 两边都转简体再比：语料里作者名是繁体（陸游），用户多半打简体（陆游），
        # 不转的话「陆游」一条都搜不到。
        keys = [hanzi.to_simplified(_WS.sub("", k)).lower()
                for k in qs.split() if k.strip()]

        def hit(b: dict) -> bool:
            hay = hanzi.to_simplified(
                b["title"] + b["author"] + b.get("dynasty", "")).lower()
            return all(k in hay for k in keys)
        books = [b for b in books if hit(b)]

    total = len(books)
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, pages))
    slice_ = books[(page - 1) * page_size: page * page_size]

    return {
        "ok": True, "query": q or "", "total": total,
        "page": page, "pages": pages, "page_size": page_size,
        "corpus_ready": True, "license": LICENSE_NOTE,
        "items": slice_,
    }


# ------------------------------------------------------------------ 成书


def chapters_of(book_id: str) -> tuple[str, str, list[tuple[str, list[str]]]]:
    """取回一本书的全部章节。返回 (书名, 作者, [(章节名, 段落)])。"""
    idx = build_index()
    book = next((b for b in idx["books"] if b["id"] == book_id), None)
    if book is None:
        raise KeyError("没有这本书：" + book_id)

    if book["kind"] == "merged":
        # 分卷的书：按卷序依次读进来，不按作者过滤
        chapters = []
        for rel in book["files"]:
            for t, ps, _ in _items_of(_read(os.path.join(CORPUS_DIR, rel))):
                chapters.append((t, ps))
    elif book["kind"] == "book":
        data = _read(os.path.join(CORPUS_DIR, book["files"][0]))
        items = _items_of(data)
        chapters = [(t or book["title"], ps) for t, ps, _ in items]
    else:
        # 别集：只在索引记下的那几个文件里找这位作者，不必重扫全库
        author = book["author"]
        chapters = []
        seen: set[tuple[str, str]] = set()
        for rel in book["files"]:
            data = _read(os.path.join(CORPUS_DIR, rel))
            for t, ps, a in _items_of(data):
                # 数据里作者名简繁不一，比对前统一成简体
                if hanzi.to_simplified(a) != author:
                    continue
                # 同一首诗在两个目录里各存一份（全唐诗 / 御定全唐詩），
                # 按「标题 + 首句」去重，不然一本集子里会读到两遍《静夜思》
                sig = (t, ps[0] if ps else "")
                if sig in seen:
                    continue
                seen.add(sig)
                chapters.append((t or f"无题{len(chapters)+1}", ps))

    return book["title"], book["author"], chapters


def build_epub(book_id: str, out_dir: str, simplified: bool = True,
               language: str = "zh") -> dict:
    """把索引条目渲染成 EPUB。

    繁体语料在这里转简体 —— 全唐诗是繁体，论语诗经本身是简体，
    hanzi 会自己判断，简体的不会被动。
    """
    title, author, chapters = chapters_of(book_id)
    if not chapters:
        return {"ok": False, "error": "这本书没有可打包的正文"}

    if simplified:
        chapters = [
            (hanzi.to_simplified(t), [hanzi.to_simplified(p) for p in ps])
            for t, ps in chapters
        ]
        title = hanzi.to_simplified(title)
        author = hanzi.to_simplified(author)

    os.makedirs(out_dir, exist_ok=True)
    name = epub_mod.safe_filename(f"{author} - {title}" if author else title) + ".epub"
    out = os.path.join(out_dir, name)

    res = epub_mod.build_epub(title, author, chapters, out, language=language)
    if not res.get("ok"):
        return res
    res.update({"book_id": book_id, "title": title, "author": author})
    return res
