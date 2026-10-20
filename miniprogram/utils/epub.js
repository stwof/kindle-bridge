// EPUB 简繁转换（在小程序里直接改 EPUB 容器的文本节点）
//
// 原则与桌面端一致：
//   · 只动文本节点 —— 标签、样式、脚本、图片、字体一律原样
//   · 产出仍是合法 EPUB：mimetype 排第一个且不压缩
//
// zip 读写用 fflate（MIT，浏览器版 CommonJS 构建）。

const { unzipSync, zipSync, strToU8, strFromU8 } = require('../vendor/fflate.js');

const TEXTUAL = ['.xhtml', '.html', '.htm', '.opf', '.ncx'];
const ANY_TAG = /<[^>]*>/g;
const SKIP_BLOCK = /<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi;
const HAS_CJK = /[㐀-鿿]/;

function isTextual(name) {
  const i = name.lastIndexOf('.');
  if (i < 0) return false;
  return TEXTUAL.indexOf(name.slice(i).toLowerCase()) >= 0;
}

// 转换标签之间的文本，标签本身一字不动
function convertBetween(seg, conv) {
  if (!seg) return seg;
  let out = '';
  let pos = 0;
  ANY_TAG.lastIndex = 0;
  let m;
  while ((m = ANY_TAG.exec(seg)) !== null) {
    out += conv(seg.slice(pos, m.index));
    out += m[0];
    pos = m.index + m[0].length;
  }
  out += conv(seg.slice(pos));
  return out;
}

// 跳过 script/style 块，只转换其余的文本
function convertMarkup(doc, conv) {
  let out = '';
  let pos = 0;
  SKIP_BLOCK.lastIndex = 0;
  let m;
  while ((m = SKIP_BLOCK.exec(doc)) !== null) {
    out += convertBetween(doc.slice(pos, m.index), conv);
    out += m[0];
    pos = m.index + m[0].length;
  }
  out += convertBetween(doc.slice(pos), conv);
  return out;
}

/**
 * 转换一个 EPUB。
 * @param {ArrayBuffer|Uint8Array} bytes  原始 EPUB
 * @param {(s:string)=>string} conv        单向转换函数
 * @returns {{bytes: Uint8Array, changed: string[], ok: boolean, error?: string}}
 */
function convertEpub(bytes, conv) {
  let files;
  try {
    files = unzipSync(bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes));
  } catch (e) {
    return { ok: false, error: '这不是一个有效的 EPUB（zip 解压失败）' };
  }
  const names = Object.keys(files);
  if (!names.length) {
    return { ok: false, error: 'EPUB 是空的' };
  }

  const converted = {};
  const changed = [];
  for (let i = 0; i < names.length; i++) {
    const name = names[i];
    const data = files[name];
    if (!data || !isTextual(name)) {
      converted[name] = data;
      continue;
    }
    let text;
    try {
      text = strFromU8(data);
    } catch (e) {
      converted[name] = data;   // 非 UTF-8 的文件不碰
      continue;
    }
    if (!HAS_CJK.test(text)) {
      converted[name] = data;
      continue;
    }
    const nt = convertMarkup(text, conv);
    if (nt !== text) {
      changed.push(name);
      converted[name] = strToU8(nt);
    } else {
      converted[name] = data;
    }
  }

  // mimetype 必须是第一个且不压缩（EPUB 规范要求）
  const entries = {};
  if (converted['mimetype']) {
    entries['mimetype'] = [converted['mimetype'], { level: 0 }];
  }
  for (let i = 0; i < names.length; i++) {
    if (names[i] !== 'mimetype') entries[names[i]] = converted[names[i]];
  }

  let out;
  try {
    out = zipSync(entries, { level: 6 });
  } catch (e) {
    return { ok: false, error: '重新打包失败：' + (e && e.message ? e.message : e) };
  }
  return { ok: true, bytes: out, changed: changed };
}

// 从 EPUB 里读出书名（dc:title），转换后要把书名一起改
function readTitle(files) {
  const names = Object.keys(files);
  for (let i = 0; i < names.length; i++) {
    const n = names[i];
    if (!/\.opf$/i.test(n)) continue;
    let text;
    try {
      text = strFromU8(files[n]);
    } catch (e) { continue; }
    const m = text.match(/<dc:title[^>]*>([\s\S]*?)<\/dc:title>/i);
    if (m) {
      return m[1].replace(/<[^>]*>/g, '').trim();
    }
  }
  return '';
}

module.exports = { convertEpub, convertMarkup, convertBetween, readTitle, isTextual };
