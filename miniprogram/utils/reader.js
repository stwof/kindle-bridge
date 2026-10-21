// 小程序原生 EPUB 阅读器内核（纯逻辑，不依赖 wx / DOM，可在 Node 里单测）
//
// 输入：EPUB 文件的二进制（Uint8Array / ArrayBuffer）
// 输出：一本「书」的结构化模型，供页面渲染：
//   {
//     title, author, language, publisher,
//     cover: { bytes, ext } | null,
//     chapters: [ { id, href, title, blocks: [ {type, text?, src?, bytes?, ext?} ] } ],
//     toc: [ { title, chapter: <章节下标>, level } ],
//     error?: string
//   }
//
// 设计取舍：
//   · 只做「能读」级别——把每章拆成 段落 / 图片 两种块（标题作为普通段落显示），
//     图片以原始字节返回（页面侧再 base64 成 data URI），不内联样式/字体。
//   · 一切坏数据都兜住：解析失败返回 { error }，不让阅读器白屏。
//   · 不依赖 DOMParser（小程序没有），用轻量正则抽取文本。

const { unzipSync, strFromU8 } = require('../vendor/fflate.js');

const BLOCK_TAGS = '(?:p|div|li|blockquote|h[1-6]|header|footer|section|article|nav|tr|td|th|dd|dt|pre)';
const IMG_RE = /<img\b[^>]*>|<image\b[^>]*>/gi;
const SRC_RE = /src\s*=\s*["']([^"']+)["']/i;
const XLINK_RE = /xlink:href\s*=\s*["']([^"']+)["']/i;
const ALT_RE = /alt\s*=\s*["']([^"']*)["']/i;
const CONTENT_RE = /<content\s+src\s*=\s*["']([^"']+)["']/i;

function unescapeXml(s) {
  if (!s) return '';
  return s
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'").replace(/&amp;/g, '&')
    .replace(/&#x([0-9a-fA-F]+);/g, (_, h) => safeChr(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => safeChr(parseInt(d, 10)));
}
function safeChr(c) {
  try { return String.fromCodePoint(c); } catch (e) { return ''; }
}
function stripTags(s) {
  return s.replace(/<[^>]*>/g, '');
}

// 把 "a/b/../c" 这类相对路径规整成从 zip 根起的路径
function resolvePath(baseDir, href) {
  const [pathPart, frag] = String(href || '').split('#');
  const parts = pathPart.split('/');
  const out = [];
  for (const p of parts) {
    if (p === '' || p === '.') continue;
    if (p === '..') out.pop();
    else out.push(p);
  }
  const joined = out.join('/');
  const full = baseDir ? baseDir + '/' + joined : joined;
  return { path: full, frag: frag || '' };
}
function dirOf(p) {
  const i = p.lastIndexOf('/');
  return i < 0 ? '' : p.slice(0, i);
}

// 大小写不敏感的 zip 索引，避免某些 EPUB 大小写不一致导致找不到文件
function buildFileIndex(files) {
  const idx = {};
  for (const name of Object.keys(files)) idx[name.toLowerCase()] = name;
  return idx;
}
function getFile(files, idx, name) {
  if (files[name] !== undefined) return files[name];
  const lower = name.toLowerCase();
  if (idx[lower] !== undefined) return files[idx[lower]];
  const n2 = name.replace(/^\/+/, '');
  if (files[n2] !== undefined) return files[n2];
  if (idx[n2.toLowerCase()] !== undefined) return files[idx[n2.toLowerCase()]];
  return null;
}
function attr(tagStr, name) {
  const m = tagStr.match(new RegExp(name + '\\s*=\\s*["\']([^"\']+)["\']', 'i'));
  return m ? m[1] : '';
}
function firstTagText(xml, tag) {
  const m = xml.match(new RegExp('<' + tag + '[^>]*>([\\s\\S]*?)</' + tag + '>', 'i'));
  return m ? m[1] : '';
}

// 把一段 XHTML 抽成块数组；图片以 { type:'img', src, bytes, ext } 形式返回
function extractBlocks(html, fileBaseDir, files, fileIdx) {
  const imgList = [];
  let s = html.replace(IMG_RE, (tag) => {
    const src = (tag.match(SRC_RE) || tag.match(XLINK_RE) || [])[1] || '';
    const i = imgList.push(src) - 1;
    return ` IMG${i} `;
  });
  s = s.replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ');
  const bodyM = s.match(/<body[^>]*>([\s\S]*)<\/body>/i);
  if (bodyM) s = bodyM[1];
  s = s.replace(new RegExp('</' + BLOCK_TAGS + '>', 'gi'), '\n')
    .replace(new RegExp('<' + BLOCK_TAGS + '\\b[^>]*>', 'gi'), '\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<hr\s*\/?>/gi, '\n');
  const blocks = [];
  const imgExt = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp']);
  for (const raw of s.split('\n')) {
    const segs = raw.split(/( IMG\d+ )/);
    for (const seg of segs) {
      const im = seg.match(/ IMG(\d+) /);
      if (im) {
        const src = imgList[+im[1]] || '';
        if (src && !/^(https?:|data:)/i.test(src)) {
          const rel = resolvePath(fileBaseDir, src).path;
          const data = getFile(files, fileIdx, rel);
          if (data) {
            const ext = (src.split('.').pop() || 'png').toLowerCase().replace(/[^a-z0-9]/g, '');
            blocks.push({ type: 'img', src, bytes: data, ext: imgExt.has(ext) ? ext : 'png' });
          }
        }
        continue;
      }
      const text = unescapeXml(stripTags(seg)).replace(/\s+/g, ' ').trim();
      if (text) blocks.push({ type: 'p', text });
    }
  }
  return blocks;
}

// EPUB2 toc.ncx：扫描 navPoint 深度，配对 content src 与最近的 text
function parseNcxToc(ncxXml) {
  const toc = [];
  let depth = -1;
  let lastText = '';
  const re = /<(\/?)navPoint\b|content\s+src\s*=\s*["']([^"']+)["']|<text>([\s\S]*?)<\/text>/gi;
  let m;
  while ((m = re.exec(ncxXml))) {
    if (m[1] === '/') { depth = Math.max(-1, depth - 1); continue; }
    if (m[0].toLowerCase().startsWith('<navpoint')) { depth++; continue; }
    if (m[2] !== undefined) {
      toc.push({
        title: lastText || ('第 ' + (toc.length + 1) + ' 节'),
        href: m[2],
        level: Math.max(0, Math.min(depth, 4)),
      });
      lastText = '';
    } else if (m[3] !== undefined) {
      lastText = unescapeXml(stripTags(m[3])).trim();
    }
  }
  return toc;
}

// EPUB3 nav 文档（<nav><ol><li><a href>…）的简化抽取
function parseNavToc(navXml) {
  const toc = [];
  const aRe = /<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;
  let m;
  while ((m = aRe.exec(navXml))) {
    const title = unescapeXml(stripTags(m[2])).replace(/\s+/g, ' ').trim();
    if (!title) continue;
    const before = navXml.slice(0, m.index);
    const opens = (before.match(/<li\b/gi) || []).length;
    const closes = (before.match(/<\/li>/gi) || []).length;
    toc.push({ title, href: m[1], level: Math.max(0, Math.min(opens - closes, 4)) });
  }
  return toc;
}

function parseEpub(input) {
  try {
    const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
    let files;
    try { files = unzipSync(bytes); }
    catch (e) { return { error: '不是合法的 EPUB（zip 解压失败）' }; }
    if (!files || !Object.keys(files).length) return { error: 'EPUB 是空的' };
    const fileIdx = buildFileIndex(files);

    const container = getFile(files, fileIdx, 'META-INF/container.xml');
    if (!container) return { error: '缺少 META-INF/container.xml' };
    const opfPath = (() => {
      const m = strFromU8(container).match(/full-path\s*=\s*["']([^"']+)["']/i);
      return m ? m[1] : null;
    })();
    if (!opfPath) return { error: 'container.xml 里没有 full-path' };
    const opfBytes = getFile(files, fileIdx, opfPath);
    if (!opfBytes) return { error: '找不到 OPF：' + opfPath };
    const opf = strFromU8(opfBytes);
    const opfDir = dirOf(opfPath);

    const title = (firstTagText(opf, 'dc:title') || firstTagText(opf, 'title') || '').trim() || '未命名';
    const author = (firstTagText(opf, 'dc:creator') || firstTagText(opf, 'creator') || '').trim();
    const language = (firstTagText(opf, 'dc:language') || '').trim();
    const publisher = (firstTagText(opf, 'dc:publisher') || '').trim();

    // manifest：id -> { href, mediaType, props }
    const manifest = {};
    const itemRe = /<item\b[^>]*>/gi;
    let it;
    while ((it = itemRe.exec(opf))) {
      const id = attr(it[0], 'id');
      if (!id) continue;
      manifest[id] = { href: attr(it[0], 'href'), mediaType: attr(it[0], 'media-type'), props: attr(it[0], 'properties') };
    }

    // spine：阅读顺序
    const spineM = opf.match(/<spine\b[^>]*>([\s\S]*?)<\/spine>/i);
    const spine = [];
    if (spineM) {
      const refRe = /<itemref\b[^>]*>/gi;
      let r;
      while ((r = refRe.exec(spineM[1]))) {
        const idref = attr(r[0], 'idref');
        if (idref && manifest[idref]) spine.push(manifest[idref]);
      }
    }
    if (!spine.length) {
      for (const id of Object.keys(manifest)) {
        if (/xhtml|html/.test(manifest[id].mediaType || '')) spine.push(manifest[id]);
      }
    }
    if (!spine.length) return { error: 'OPF 里没有可阅读的章节' };

    // 封面
    let cover = null;
    const coverId = (() => {
      const m = opf.match(/<meta\s+name\s*=\s*["']cover["'][^>]*content\s*=\s*["']([^"']+)["']/i);
      return m ? m[1] : null;
    })();
    const tryCover = (item) => {
      if (!item) return false;
      const cov = resolvePath(opfDir, item.href);
      const covBytes = getFile(files, fileIdx, cov.path);
      if (covBytes) { cover = { bytes: covBytes, ext: (item.href.split('.').pop() || 'jpg').toLowerCase() }; return true; }
      return false;
    };
    if (coverId) tryCover(manifest[coverId]);
    if (!cover) {
      for (const id of Object.keys(manifest)) {
        if (/cover-image/.test(manifest[id].props)) { if (tryCover(manifest[id])) break; }
      }
    }

    // 章节
    const chapters = [];
    const hrefToIndex = {};
    spine.forEach((item, idx) => {
      const r = resolvePath(opfDir, item.href);
      const data = getFile(files, fileIdx, r.path);
      const base = dirOf(r.path);
      let blocks = [];
      if (data) blocks = extractBlocks(strFromU8(data), base, files, fileIdx);
      const key = r.path.split('#')[0].toLowerCase();
      if (!(key in hrefToIndex)) hrefToIndex[key] = idx;
      chapters.push({ id: 'ch' + idx, href: r.path, title: '', blocks });
    });

    // TOC
    let toc = [];
    const ncxItem = Object.keys(manifest).find((id) => /dtbncx/.test(manifest[id].mediaType));
    if (ncxItem) {
      const ncxBytes = getFile(files, fileIdx, resolvePath(opfDir, manifest[ncxItem].href).path);
      if (ncxBytes) toc = parseNcxToc(strFromU8(ncxBytes));
    }
    if (!toc.length) {
      const navId = Object.keys(manifest).find((id) => /nav/.test(manifest[id].props));
      if (navId) {
        const navBytes = getFile(files, fileIdx, resolvePath(opfDir, manifest[navId].href).path);
        if (navBytes) toc = parseNavToc(strFromU8(navBytes));
      }
    }
    toc = toc.map((t) => {
      const key = resolvePath(opfDir, t.href).path.split('#')[0].toLowerCase();
      const chapter = hrefToIndex[key];
      return { title: t.title, href: t.href, level: t.level || 0, chapter: chapter === undefined ? -1 : chapter };
    });
    // ncx/nav 抽出来只有 1 条（常见是古登堡的版权/许可页）时，不如退回按章节顺序生成目录
    if (toc.length < 2) {
      toc = chapters.map((c, i) => ({ title: '第 ' + (i + 1) + ' 章', href: c.href, level: 0, chapter: i }));
    }
    toc.forEach((t) => { if (t.chapter >= 0 && !chapters[t.chapter].title) chapters[t.chapter].title = t.title; });
    chapters.forEach((c, i) => { if (!c.title) c.title = '第 ' + (i + 1) + ' 章'; });

    return { title, author, language, publisher, cover, chapters, toc };
  } catch (e) {
    return { error: '解析失败：' + (e && e.message ? e.message : String(e)) };
  }
}

module.exports = { parseEpub, unescapeXml, stripTags, resolvePath };
