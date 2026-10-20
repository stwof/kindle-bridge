// 生词处理 —— 解析桌面端导出的《Kindle生词本.csv》，再转成 Anki / Markdown / JSON。
//
// 为什么不是直接读 vocab.db：那是 Kindle 上的 SQLite 库，
// 微信小程序读不了二进制数据库。先在电脑的「生词」页导出 CSV，
// 再传到微信里用这个页面转成 Anki 词库即可。
//
// CSV 列：单词, 语言, 查询次数, 最近查询, 首条例句, 出处

// 解析一行 CSV（支持双引号包裹、字段里的逗号与换行）
function parseCsvLine(line) {
  const out = [];
  let cur = '';
  let inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuote) {
      if (ch === '"') {
        if (line[i + 1] === '"') { cur += '"'; i++; }
        else inQuote = false;
      } else cur += ch;
    } else if (ch === '"') {
      inQuote = true;
    } else if (ch === ',') {
      out.push(cur); cur = '';
    } else {
      cur += ch;
    }
  }
  out.push(cur);
  return out;
}

// 解析整份 CSV（支持字段内换行）
function parseCsv(text) {
  if (!text) return [];
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);   // 去 BOM
  const rows = [];
  let cur = [];
  let field = '';
  let inQuote = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuote) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuote = false;
      } else field += ch;
    } else if (ch === '"') {
      inQuote = true;
    } else if (ch === ',') {
      cur.push(field); field = '';
    } else if (ch === '\n') {
      cur.push(field); field = '';
      if (cur.length > 1 || cur[0] !== '') rows.push(cur);
      cur = [];
    } else if (ch !== '\r') {
      field += ch;
    }
  }
  if (field.length || cur.length) {
    cur.push(field);
    if (cur.length > 1 || cur[0] !== '') rows.push(cur);
  }
  return rows;
}

// CSV -> 结构化词条
function parseVocabCsv(text) {
  const rows = parseCsv(text);
  if (!rows.length) return { words: [], header: [] };
  const header = rows[0].map((h) => h.trim());
  const words = [];
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    if (!r.length || !r[0]) continue;
    words.push({
      word: r[0] || '',
      lang: (r[1] || '').indexOf('中文') >= 0 ? 'zh' : 'en',
      lookups: +(r[2] || 0) || 0,
      last_lookup: r[3] || '',
      context: r[4] || '',
      book: r[5] || ''
    });
  }
  return { words: words, header: header };
}

// Anki 导入格式（正面 / 背面 / 标签，制表符分隔）—— 与桌面端一致
function toAnki(words) {
  let out = '#separator:tab\n#html:false\n#columns:正面\t背面\t标签\n';
  for (const w of words) {
    let back = w.context || '';
    if (w.book) {
      back = back ? back + '\n——《' + w.book + '》' : '——《' + w.book + '》';
    }
    const tag = 'kindle ' + (w.lang === 'zh' ? '中文' : '英文');
    out += w.word + '\t' + back + '\t' + tag + '\n';
  }
  return out;
}

// Markdown 词表
function toMarkdown(words) {
  let out = '# Kindle 生词本\n\n共 ' + words.length + ' 个词。\n\n';
  out += '| 单词 | 语言 | 次数 | 最近查询 | 例句 | 出处 |\n';
  out += '| --- | --- | --- | --- | --- | --- |\n';
  for (const w of words) {
    const cell = (s) => String(s || '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
    out += '| ' + cell(w.word) + ' | ' + (w.lang === 'zh' ? '中文' : '英文') +
      ' | ' + w.lookups + ' | ' + cell(w.last_lookup) +
      ' | ' + cell(w.context) + ' | ' + cell(w.book) + ' |\n';
  }
  return out;
}

// JSON
function toJson(words) {
  return JSON.stringify({
    generator: 'Kindle 桥 · 微信小程序',
    count: words.length,
    words: words
  }, null, 2);
}

module.exports = { parseCsv, parseVocabCsv, toAnki, toMarkdown, toJson };
