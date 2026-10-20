// 简繁转换的「补丁表」—— 与桌面端 kindle/hanzi.py 保持一致。
//
// OpenCC 的字典已经很全，但仍有少量冷僻字与异体字没覆盖（擡/舖/薴…），
// 以及少量「按语义必须保留繁体」的词（乾坤/變徵…）。这里补上，
// 保证手机上的结果和电脑上一致。

// 繁 -> 简：异体/冷僻字 -> 标准简体。只在 OpenCC 没转的字符上生效。
const SUPP_T2S = {
  '擡': '抬', '舖': '铺', '恠': '怪', '竝': '并', '靑': '青', '睂': '眉',
  '羣': '群', '旾': '春', '迃': '迂', '秌': '秋', '僊': '仙', '巖': '岩',
  '涙': '泪', '棄': '弃', '異': '异', '週': '周', '甦': '苏', '麪': '面',
  '菓': '果', '卽': '即', '効': '效', '刄': '刃', '兎': '兔', '砲': '炮',
  '羮': '羹', '谿': '溪', '虖': '呼', '艸': '草', '咊': '和', '灋': '法',
  '栞': '刊', '祕': '秘', '竪': '竖', '甆': '瓷', '敓': '夺', '敍': '叙',
  '煑': '煮', '煖': '暖', '烖': '灾', '玅': '妙', '盡': '尽', '盃': '杯',
  '眞': '真', '筭': '算', '罸': '罚', '羗': '羌',
  '苧': '苎'   // 薴->苧 是第一跳，苧->苎 这一跳 OpenCC 不做
};

// 繁 -> 简：这些词里的字不能一刀切，要保住繁体。
// 例：五声音阶「宫商角徵羽」的徵(zhǐ)不是「征」；「乾坤」也不能变「干坤」。
const KEEP_T2S = {
  '變徵': '变徵'
};

// 用 Unicode 私用区字符当哨兵：它不在任何字典里，转换时必然原样穿过。
const SENT_A = String.fromCharCode(0xE000);
const SENT_B = String.fromCharCode(0xE001);

// 把补丁套在 OpenCC 的输出上（异体替换）。
function applySupp(text) {
  if (!text) return text;
  let out = '';
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    out += SUPP_T2S[ch] || ch;
  }
  return out;
}

// 转换前把要保住的词换成哨兵，转换后再还原。
function protect(text, mapping) {
  const keys = Object.keys(mapping);
  if (!keys.length || !text) return { text: text || '', store: [] };
  const store = [];
  let out = text;
  // 长的词优先，避免「變徵」被更短的词先吃掉
  keys.sort((a, b) => b.length - a.length);
  for (let i = 0; i < keys.length; i++) {
    const k = keys[i];
    if (out.indexOf(k) < 0) continue;
    out = out.split(k).join(SENT_A + store.length + SENT_B);
    store.push(mapping[k]);
  }
  return { text: out, store: store };
}

function restore(text, store) {
  let out = text;
  for (let i = 0; i < store.length; i++) {
    out = out.split(SENT_A + i + SENT_B).join(store[i]);
  }
  return out;
}

module.exports = { SUPP_T2S, KEEP_T2S, applySupp, protect, restore };
