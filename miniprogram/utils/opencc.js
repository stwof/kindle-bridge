// 简繁转换封装（繁 -> 简）
//
// 字典来自 opencc-js（OpenCC 的 JavaScript 实现，Apache-2.0），
// 压缩后约 107KB，放在主包里，打开就能用，不用联网。
// 简 -> 繁 需要 1MB 的词组表，放不进主包，所以放在分包 pkg-trad 里按需加载。
//
// 注意：这里的转换是纯本地计算，文本不会离开手机。

const OpenCC = require('../vendor/t2cn.js');
const tables = require('./zhtables.js');

let _conv = null;

function rawConverter() {
  if (!_conv) {
    // hk -> cn：香港正体转大陆简体。
    // 为什么不是 tw（台湾）？tw 口径会把「著」一律转成「着」（著名→着名），
    // 还把「么」转成「幺」，与桌面端的标准 t2s 差出好几千处。
    // hk 口径与桌面端逐字比对只差十来个港台异体字，且那几个（如袷→夹）
    // 对大陆读者反而更正确。
    _conv = OpenCC.Converter({ from: 'hk', to: 'cn' });
  }
  return _conv;
}

// 繁体 -> 简体（含异体补丁与短语保护）
function t2s(text) {
  if (!text) return '';
  const g = tables.protect(text, tables.KEEP_T2S);
  const out = tables.applySupp(rawConverter()(g.text));
  return tables.restore(out, g.store);
}

// 文本里「繁体字」的比例（0~1）。
// 判据直接用字典本身：某个字经 t2s 会变，说明它是繁体字 —— 不用手工维护字表。
function tradRatio(text) {
  if (!text) return 0;
  const conv = rawConverter();
  const sample = text.length > 20000 ? text.slice(0, 20000) : text;
  const isTrad = new Map();
  let total = 0;
  let trad = 0;
  for (let i = 0; i < sample.length; i++) {
    const ch = sample[i];
    const code = sample.charCodeAt(i);
    if (code < 0x4e00 || code > 0x9fff) continue;
    total++;
    if (!isTrad.has(ch)) {
      isTrad.set(ch, conv(ch) !== ch);
    }
    if (isTrad.get(ch)) trad++;
  }
  return total ? trad / total : 0;
}

// 自动判别：返回 'traditional' / 'simplified' / 'unknown'
function detect(text) {
  if (!text) return 'unknown';
  const r = tradRatio(text);
  if (r > 0.02) return 'traditional';
  if (r < 0.002) return 'simplified';
  return 'unknown';
}

module.exports = { t2s, tradRatio, detect };
