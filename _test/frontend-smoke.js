/* 在 Node 里用最小 DOM 桩真实执行 app.js，喂真实接口数据，抓运行时报错。 */
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE || 'http://127.0.0.1:8791';
const errors = [];

function makeEl(tag) {
  const e = {
    tagName: (tag || 'div').toUpperCase(),
    _html: '', _text: '', children: [], _handlers: {},
    className: '', id: '', type: '', value: '', checked: false,
    disabled: false, hidden: false, href: '', download: '', files: null,
    style: {}, dataset: {},
    classList: {
      _s: new Set(),
      add(...c) { c.forEach((x) => this._s.add(x)); },
      remove(...c) { c.forEach((x) => this._s.delete(x)); },
      toggle(c, f) { if (f === undefined) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); } else { f ? this._s.add(c) : this._s.delete(c); } },
      contains(c) { return this._s.has(c); },
    },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { this.children = this.children.filter((x) => x !== c); },
    remove() {},
    click() {},
    set innerHTML(v) { this._html = String(v); this.children = []; },
    get innerHTML() { return this._html; },
    set textContent(v) { this._text = String(v); },
    get textContent() { return this._text; },
    addEventListener(ev, fn) { (this._handlers[ev] = this._handlers[ev] || []).push(fn); },
    querySelector(sel) { return document.querySelector(sel); },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
  };
  return e;
}

const TABS = ['library', 'epub', 'free', 'highlights', 'vocab', 'export', 'guide']
  .map((t) => { const e = makeEl('button'); e.dataset.tab = t; return e; });

const cache = new Map();
const document = {
  querySelector(sel) {
    if (!cache.has(sel)) cache.set(sel, makeEl(sel.split(/[ #.]/)[0] || 'div'));
    return cache.get(sel);
  },
  querySelectorAll(sel) { return sel === '.tab' ? TABS : []; },
  createElement: makeEl,
  body: makeEl('body'),
  addEventListener() {},
};

global.document = document;
global.window = { open() { return null; }, addEventListener() {} };
global.location = { href: BASE + '/', reload() {} };
global.URL.createObjectURL = () => 'blob:x';
global.URL.revokeObjectURL = () => {};
global.clearTimeout = () => {};
global.requestAnimationFrame = (f) => setTimeout(f, 0);

process.on('unhandledRejection', (r) => errors.push('未处理的 Promise 拒绝: ' + (r && r.message || r)));
process.on('uncaughtException', (e) => errors.push('未捕获异常: ' + e.message));

// 把相对路径的 fetch 指到本地服务
const realFetch = global.fetch;
global.fetch = (u, o) => realFetch(u.startsWith('http') ? u : BASE + u, o);

const src = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
try {
  new Function(src)();          // app.js 是 IIFE，执行即 bind() + load()
  console.log('  app.js 顶层执行：无异常');
} catch (e) {
  errors.push('顶层执行抛错: ' + e.message);
}

setTimeout(async () => {  console.log('\n=== 页面状态检查 ===');
  const dev = document.querySelector('#devtext').textContent;
  console.log('  顶栏设备文案:', dev || '(空)');
  if (/读取失败/.test(dev)) errors.push('load() 走进了 catch：' + dev);

  const hints = [
    ['#epub-hint', 'EPUB 提示'],
    ['#libhint', '书库提示'],
    ['#hintips', '标注提示'],
    ['#vhint', '生词提示'],
  ];
  for (const [sel, label] of hints) {
    const v = document.querySelector(sel).innerHTML;
    console.log(`  ${label}:`, v ? v.replace(/<[^>]+>/g, '').slice(0, 84) : '(空)');
    if (!v) errors.push(`${label} 未被渲染`);
  }

  const routes = document.querySelector('#epub-routes').children.length;
  console.log('  路线卡片数:', routes);
  if (routes !== 4) errors.push('路线卡片应为 4 张，实际 ' + routes);

  // 路线 D 按钮存在，且 MOBI 家族存在时可用
  const nativeBtn = document.querySelector('#epub-native');
  const azw3Btn = document.querySelector('#epub-azw3');
  console.log('  #epub-native 存在:', !!nativeBtn, '| disabled:', nativeBtn.disabled);
  console.log('  #epub-azw3   disabled:', azw3Btn.disabled, '(无 Calibre 时应为 true)');

  const erows = document.querySelector('#epub-table tbody').children.length;
  console.log('  收书表格行数:', erows);

  // 路线 A 环境卡片
  const calState = document.querySelector('#cal-state').textContent;
  const calBody = document.querySelector('#cal-body').children.length;
  console.log('  Calibre 状态文案:', calState || '(空)');
  console.log('  Calibre 卡体节点数:', calBody);
  if (!calState || calState === '检测中…') errors.push('Calibre 状态未被渲染：' + calState);
  if (!calBody) errors.push('Calibre 引导内容未渲染');

  const stats = document.querySelector('#stats').children.length;
  console.log('  统计卡数:', stats);
  if (stats !== 5) errors.push('统计卡应为 5 张，实际 ' + stats);

  const rows = document.querySelector('#libtable tbody').children.length;
  console.log('  书库表格行数:', rows);

  const cards = document.querySelector('#export-cards').children.length;
  console.log('  导出卡片数:', cards);
  if (cards !== 7) errors.push('导出卡片应为 7 张，实际 ' + cards);

  console.log('\n=== 公版书库（真实检索）===');
  const freeTab = TABS.find((t) => t.dataset.tab === 'free');
  (freeTab._handlers.click || []).forEach((f) => f());
  console.log('  已切到「公版书库」标签，点击后触发检索');

  const chips = document.querySelector('#free-chips').children.length;
  console.log('  快捷词条数:', chips);
  if (chips !== 9) errors.push('快捷词条应为 9 个，实际 ' + chips);

  // 线路被下载任务占满时，检索最多要等 SEARCH_DEADLINE 那一拍
  for (let i = 0; i < 70; i++) {
    await new Promise((r) => setTimeout(r, 500));
    const s = document.querySelector('#free-state').textContent;
    if (s && s.indexOf('检索中') < 0) break;
  }
  const fstate = document.querySelector('#free-state').textContent;
  const grid = document.querySelector('#free-gridbox');
  const cards2 = (grid.children[0] && grid.children[0].className === 'bk-grid')
    ? grid.children[0].children.length : 0;
  console.log('  状态:', fstate);
  console.log('  结果卡片数:', cards2);
  if (/检索失败/.test(fstate)) errors.push('公版书库检索失败：' + fstate);
  if (!cards2) errors.push('公版书库没渲染出任何结果卡片');
  if (cards2) {
    const first = grid.children[0].children[0];
    const collect = (n) => [n._text || '', n._html || ''].concat((n.children || []).flatMap(collect));
    const txt = collect(first).join(' ');
    console.log('  首张卡片摘要:', txt.replace(/\s+/g, ' ').slice(0, 150));
    if (txt.indexOf('取回') < 0) errors.push('结果卡片上没有「取回」按钮');
    if (txt.indexOf('在源站查看') < 0) errors.push('结果卡片上没有源站链接');
  }

  console.log('\n=== 结果 ===');
  if (errors.length) {
    errors.forEach((e) => console.log('  ★ ' + e));
    process.exit(1);
  }
  console.log('  全部通过：无 JS 运行时报错，各面板均渲染成功 ✓');
  process.exit(0);
}, 2500);
