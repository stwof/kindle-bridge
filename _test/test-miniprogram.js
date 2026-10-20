// 小程序侧的转换内核自测（不需要微信开发者工具，直接 node 跑）
//
//   node _test/test-miniprogram.js
//
// 验证：主包/分包的字典都能用、异体补丁与短语保护生效、
//       EPUB 转换只动文本节点且容器合法、转换结果与桌面端口径一致。

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const MP = path.join(__dirname, '..', 'miniprogram');
const zh = require(path.join(MP, 'utils', 'opencc.js'));
const eu = require(path.join(MP, 'utils', 'epub.js'));
const cl = require(path.join(MP, 'utils', 'clippings.js'));
const vc = require(path.join(MP, 'utils', 'vocab.js'));
const { unzipSync, zipSync, strToU8, strFromU8 } = require(path.join(MP, 'vendor', 'fflate.js'));

let pass = 0;
let fail = 0;

function chk(cond, msg) {
  if (cond) { pass++; console.log('  [OK]   ' + msg); }
  else { fail++; console.log('  [FAIL] ' + msg); }
}

console.log('\n=== A. 简繁转换（主包 繁->简）===');
chk(zh.t2s('我們在這裡讀書') === '我们在这里读书', '繁体转简体');
chk(zh.t2s('頭髮乾淨') === '头发干净', '头发/干净 一对多消歧');
chk(zh.t2s('公里里程') === '公里里程', '公里 不误转成 公里');
chk(zh.t2s('皇后太后') === '皇后太后', '皇后/太后 不误转');
chk(zh.t2s('擡') === '抬', '异体补丁：擡 -> 抬');
chk(zh.t2s('舖') === '铺', '异体补丁：舖 -> 铺');
chk(zh.t2s('薴') === '苎', '链式补全：薴 -> 苧 -> 苎');
chk(zh.t2s('乾坤再造之恩') === '乾坤再造之恩', '乾坤 的「乾」保留');
chk(zh.t2s('變徵之聲') === '变徵之声', '變徵 的「徵」保留');
chk(zh.t2s('宮商角徵羽') === '宫商角徵羽', '宫商角徵羽 不被误转');
chk(zh.t2s('English text') === 'English text', '英文原样');
chk(zh.detect('我們在這裡讀書') === 'traditional', 'detect 繁体');
chk(zh.detect('我们在在这里读书') === 'simplified', 'detect 简体');

console.log('\n=== B. 简繁转换（分包 简->繁）===');
const OpenCC2 = require(path.join(MP, 'pkg-trad', 'vendor', 'cn2t.js'));
const s2t = OpenCC2.Converter({ from: 'cn', to: 'twp' });
chk(s2t('我们在这里读书') === '我們在這裡讀書', '简体转台湾正体');
chk(s2t('头发干净') === '頭髮乾淨', '头发 -> 頭髮');
chk(s2t('网络软件') === '網路軟體', '网络软件 -> 網路軟體（台湾用词）');
chk(s2t('公里里程') === '公里里程', '公里 不误转成 公裡');

console.log('\n=== C. EPUB 容器转换 ===');
const sample = {
  'mimetype': strToU8('application/epub+zip'),
  'OEBPS/ch1.xhtml': strToU8(
    '<?xml version="1.0" encoding="utf-8"?>\n' +
    '<html xmlns="http://www.w3.org/1999/xhtml"><head>' +
    '<style>.a{font-family:"標楷體"}</style>' +
    '<script>var s="這是腳本";</script></head><body>' +
    '<p>我們在這裡讀書，頭髮乾淨，裡面有人，乾坤不變。</p>' +
    '<p>扛擡到店舖，薴布一匹。</p>' +
    '</body></html>'),
  'OEBPS/cover.png': new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])
};
const zip = zipSync(sample, { level: 6 });
const r = eu.convertEpub(zip, zh.t2s);
chk(r.ok, 'EPUB 转换成功');
const out = unzipSync(r.bytes);
const names = Object.keys(out);
chk(names[0] === 'mimetype', 'mimetype 排在首位');
chk(strFromU8(out['mimetype']) === 'application/epub+zip', 'mimetype 内容正确');
const chap = strFromU8(out['OEBPS/ch1.xhtml']);
chk(chap.indexOf('我们在ide读书') < 0 && chap.indexOf('我们在这里读书') >= 0, '正文已转简体');
chk(chap.indexOf('头发干净') >= 0, '正文 头发/干净 正确');
chk(chap.indexOf('里面有人') >= 0, '正文 里面 正确');
chk(chap.indexOf('乾坤不变') >= 0, '乾坤 保留');
chk(chap.indexOf('变徵') < 0, '无 变徵 误转');
chk(chap.indexOf('扛抬到店铺') >= 0, '扛抬 / 店铺 异体已转');
chk(chap.indexOf('苎布一匹') >= 0, '薴 -> 苎 链式补全');
chk(chap.indexOf('font-family:"標楷體"') >= 0, 'style 内繁体被保护');
chk(chap.indexOf('var s="這是腳本";') >= 0, 'script 内繁体被保护');
chk(out['OEBPS/cover.png'] && out['OEBPS/cover.png'].length === 8, '图片字节原样保留');

console.log('\n=== D. 标注解析 ===');
const clipsRaw = [
  '红楼梦 (曹雪芹)',
  '- Your Highlight on page 12 | Location 3749-3750 | Added on Monday, January 1, 2024 10:00:00',
  '满纸荒唐言，一把辛酸泪。',
  '==========',
  '红楼梦 (曹雪芹)',
  '- 你的笔记 on page 20 | location 4000 | Added on 2024年1月2日 上午 9:05:00',
  '批注内容',
  '=========='
].join('\n');
const clips = cl.parseClippings(clipsRaw, true);
chk(clips.length === 2, '解析出 2 条标注，实际 ' + clips.length);
chk(clips[0].title === '红楼梦', '书名解析：红楼梦');
chk(clips[0].author === '曹雪芹', '作者解析：曹雪芹');
chk(clips[0].type === 'highlight', '类型解析：highlight');
chk(clips[0].page === '12', '页码解析：12');
chk(clips[0].location === '3749-3750', '位置解析：3749-3750');
chk(clips[0].added_at === '2024-01-01 10:00:00', '英文时间解析：' + clips[0].added_at);
chk(clips[1].type === 'note', '类型解析：note');
chk(clips[1].added_at === '2024-01-02 09:05:00', '中文时间解析：' + clips[1].added_at);
const groups = cl.groupByBook(clips);
chk(groups.length === 1 && groups[0].items.length === 2, '按书分组');

console.log('\n=== E. 生词 CSV ===');
const csv = '单词,语言,查询次数,最近查询,首条例句,出处\r\n' +
  '惆怅,中文,3,2024-01-01 10:00:00,"他说,心里有点惆怅",红楼梦\r\n' +
  'elephant,英文,1,2024-01-02 11:00:00,A big elephant,English Book\r\n';
const v = vc.parseVocabCsv(csv);
chk(v.words.length === 2, '解析出 2 个词，实际 ' + v.words.length);
chk(v.words[0].word === '惆怅', '中文词解析');
chk(v.words[0].lookups === 3, '查询次数解析');
chk(v.words[0].context === '他说,心里有点惆怅', '带逗号的例句解析正确');
chk(v.words[1].lang === 'en', '英文词标记');
const anki = vc.toAnki(v.words);
chk(anki.indexOf('#columns:正面\t背面\t标签') >= 0, 'Anki 表头正确');
chk(anki.indexOf('惆怅\t他说,心里有点惆怅\n——《红楼梦》\tkindle 中文') >= 0, 'Anki 行格式正确');

console.log('\n==============================================');
console.log('通过 ' + pass + ' 项，失败 ' + fail + ' 项');
process.exit(fail ? 1 : 0);
