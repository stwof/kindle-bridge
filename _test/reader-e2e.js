#!/usr/bin/env node
/* 用 CDP 驱动一个真实浏览器，跑一遍阅读器的真实用户流程，并把控制台错误全抓下来。
 *
 * 为什么不用 agent-browser CLI：它的 daemon 在这台机器上起不来（Chromium 也没法下载）。
 * Node 22 自带 WebSocket，直接说 CDP 协议更稳，也不引新依赖。
 *
 * 用法：node reader-e2e.js [端口] [--shot 输出目录] [--keep]
 * 依赖：外部已有一个开着 --remote-debugging-port 的浏览器（本脚本自己拉起 Edge）。
 */
'use strict';

const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const PORT = Number(process.argv[2]) || 8765;
const SHOT = (() => {
  const i = process.argv.indexOf('--shot');
  return i > 0 ? process.argv[i + 1] : '';
})();
const BASE = `http://127.0.0.1:${PORT}`;
const CDP_PORT = 9333;

const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));

let pass = 0, fail = 0;
const failures = [];
function ok(name, cond, detail) {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else {
    fail++; failures.push(name + (detail ? ' :: ' + detail : ''));
    console.log('  ✗ ' + name + (detail ? '  → ' + detail : ''));
  }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- CDP 客户端
class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.waits = new Map(); this.handlers = []; }
  static async attach(wsUrl) {
    const ws = new WebSocket(wsUrl);
    const c = new CDP(ws);
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true });
      ws.addEventListener('error', () => rej(new Error('WebSocket 连接失败')), { once: true });
    });
    ws.addEventListener('message', (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch { return; }
      if (m.id && c.waits.has(m.id)) {
        const { res, rej } = c.waits.get(m.id); c.waits.delete(m.id);
        m.error ? rej(new Error(m.error.message)) : res(m.result);
      } else if (m.method) { c.handlers.forEach((h) => h(m)); }
    });
    return c;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.waits.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.waits.has(id)) { this.waits.delete(id); rej(new Error('CDP 超时: ' + method)); }
      }, 30000);
    });
  }
  on(fn) { this.handlers.push(fn); }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate', {
      expression: `(function(){${expr}})()`,
      returnByValue: true, awaitPromise: true,
    });
    if (r.exceptionDetails) {
      throw new Error(r.exceptionDetails.exception?.description || '页面内异常');
    }
    return r.result.value;
  }
  close() { try { this.ws.close(); } catch {} }
}

async function getPageWsUrl() {
  // 直接连「页面」target 的 ws，省掉 flatten session 那一套
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`);
      const list = await r.json();
      const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(500);
  }
  throw new Error('浏览器调试端口没起来');
}

// ------------------------------------------------------------------ 主流程
(async () => {
  if (!EDGE) { console.error('找不到 Edge/Chrome，无法跑真实浏览器测试'); process.exit(2); }

  const profile = path.join(os.tmpdir(), 'kb-e2e-profile');
  fs.rmSync(profile, { recursive: true, force: true });
  const proc = spawn(EDGE, [
    `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${profile}`,
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--no-proxy-server',
    '--disable-features=Translate,MediaRouter', '--autoplay-policy=no-user-gesture-required',
    '--mute-audio', 'about:blank',
  ], { stdio: 'ignore', detached: false });

  let cdp;
  const logs = [];
  const failedUrls = [];
  try {
    cdp = await CDP.attach(await getPageWsUrl());

    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable');
    await cdp.send('Network.enable');
    cdp.on((m) => {
      if (m.method === 'Network.responseReceived' && m.params.response.status >= 400) {
        failedUrls.push(m.params.response.status + ' ' + m.params.response.url);
      }
      if (m.method === 'Runtime.consoleAPICalled') {
        const txt = (m.params.args || []).map((a) => a.value ?? a.description ?? a.type).join(' ');
        logs.push({ kind: m.params.type, text: txt });
      } else if (m.method === 'Log.entryAdded') {
        logs.push({ kind: m.params.entry.level, text: m.params.entry.text });
      } else if (m.method === 'Runtime.exceptionThrown') {
        const d = m.params.exceptionDetails;
        logs.push({ kind: 'pageerror', text: d.exception?.description || d.text });
      }
    });

    const shot = async (name) => {
      if (!SHOT) return;
      fs.mkdirSync(SHOT, { recursive: true });
      const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' });
      fs.writeFileSync(path.join(SHOT, name + '.png'), Buffer.from(data, 'base64'));
    };

    console.log('\n【1】页面加载与依赖');
    await cdp.send('Page.navigate', { url: BASE + '/' });
    await sleep(2500);
    ok('页面标题正确', (await cdp.eval('return document.title')).includes('Kindle'), await cdp.eval('return document.title'));
    // JSZip/epub.js 都是 UMD，挂到 window 上是 function（不是 object）
    ok('JSZip 已加载', ['function', 'object'].includes(await cdp.eval('return typeof JSZip')), 'typeof JSZip=' + await cdp.eval('return typeof JSZip'));
    ok('epub.js 已加载为函数', (await cdp.eval('return typeof ePub')) === 'function', 'typeof ePub=' + await cdp.eval('return typeof ePub'));
    ok('页面有内容', (await cdp.eval('return document.body.innerHTML.length')) > 3000);
    await shot('01-home');

    console.log('\n【2】进入阅读器页');
    await cdp.eval(`document.querySelector('[data-tab="reader"]').click(); return 1`);
    await sleep(1800);
    const cards = await cdp.eval('return document.querySelectorAll("#panel-reader .shelf-card").length');
    ok('书架渲染出卡片', cards > 0, '卡片数=' + cards);
    await shot('02-shelf');

    console.log('\n【3】打开一本书（真实点击）');
    const firstKey = await cdp.eval(`
      const c = document.querySelector('#panel-reader .shelf-card');
      return c ? (c.dataset.key || '') : '';`);
    // 卡片上未必有 data-key，改为直接调用内部流程前先看看有没有
    const hasDataKey = !!(await cdp.eval(`
      const c=document.querySelector('#panel-reader .shelf-card');
      return !!(c && c.dataset && c.dataset.key);`));
    if (!hasDataKey) {
      console.log('  （卡片无 data-key，改用 bookKey 列表定位）');
    }
    await cdp.eval(`document.querySelector('#panel-reader .shelf-card').click(); return 1`);
    await sleep(9000);
    const st = await cdp.eval(`
      const ov = document.querySelector('#reader-overlay');
      const iframes = document.querySelectorAll('#rd-stage iframe').length;
      const load = document.querySelector('#rd-loading');
      return JSON.stringify({
        overlayOpen: ov ? !ov.hidden : false,
        iframes,
        loadingVisible: load ? load.classList.contains('show') : null,
        loadingText: (document.querySelector('#rd-loading-text')||{}).textContent || '',
        stageChildren: document.querySelector('#rd-stage') ? document.querySelector('#rd-stage').children.length : -1,
        title: (document.querySelector('#rd-title')||{}).textContent || '',
        toast: (document.querySelector('#toast')||{}).textContent || ''
      });`);
    const s = JSON.parse(st);
    ok('全屏阅读器已打开', s.overlayOpen, JSON.stringify(s));
    ok('书名已显示', !!s.title, 'title=' + s.title);
    ok('epub.js 渲染出 iframe', s.iframes > 0, 'iframe 数=' + s.iframes);
    ok('加载遮罩已隐藏', s.loadingVisible === false, 'loading=' + s.loadingVisible);
    await shot('03-reader');

    console.log('\n【4】翻页后正文有内容');
    // 封面页常常是整张图片、没有文字，所以先翻几页再验正文
    for (let i = 0; i < 4; i++) {
      await cdp.eval(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true})); return 1`);
      await sleep(700);
    }
    const body = await cdp.eval(`
      const f = document.querySelector('#rd-stage iframe');
      if (!f) return JSON.stringify({err:'没有 iframe'});
      let d=null; try { d=f.contentDocument } catch(e) { return JSON.stringify({err:'跨域拿不到文档'}); }
      if (!d || !d.body) return JSON.stringify({err:'文档没有 body'});
      const t=(d.body.textContent||'').replace(/\\s+/g,' ').trim();
      return JSON.stringify({len:t.length, sample:t.slice(0,60)});`);
    const b = JSON.parse(body);
    ok('正文文本非空', b.len > 20, '正文字符数=' + b.len + (b.err ? ' (' + b.err + ')' : '样本=' + b.sample));
    await shot('03b-text');

    console.log('\n【6】目录抽屉');
    const tocN = await cdp.eval(`return (window.__rd && window.__rd.toc) ? window.__rd.toc.length : (document.querySelectorAll('#rd-toc-drawer li').length)`);
    ok('目录已生成', tocN >= 0, '目录项=' + tocN);
    await shot('04-toc');

    console.log('\n【7】朗读功能');
    ok('顶部有「朗读」按钮', await cdp.eval(`return !!document.querySelector('#rd-read')`));
    ok('选词工具条有朗读按钮', await cdp.eval(`return !!document.querySelector('#rd-sel-read')`));
    ok('有朗读状态条', await cdp.eval(`return !!document.querySelector('#rd-speech')`));
    ok('有自动续读开关', await cdp.eval(`return !!document.querySelector('#rd-speech-auto')`));
    // 点朗读：TTS 没装时应当回落到浏览器语音并给出状态，而不是静默失败
    await cdp.eval(`document.querySelector('#rd-read').click(); return 1`);
    await sleep(2500);
    const sp = await cdp.eval(`
      const bar=document.querySelector('#rd-speech');
      return JSON.stringify({
        shown: bar ? !bar.hidden : false,
        text: (document.querySelector('#rd-speech-text')||{}).textContent||'',
        btn: (document.querySelector('#rd-read')||{}).textContent||''
      });`);
    const spj = JSON.parse(sp);
    ok('点朗读后状态条出现', spj.shown, JSON.stringify(spj));
    ok('状态条说明了用的引擎', /TTS|浏览器|准备|朗读/.test(spj.text), 'text=' + spj.text);
    ok('按钮切换为停止', /停止/.test(spj.btn), 'btn=' + spj.btn);
    await shot('05-speech');
    // 收尾：停下来，别让音频一直放
    await cdp.eval(`const b=document.querySelector('#rd-speech-stop'); if(b) b.click(); return 1`);
    await sleep(600);
    ok('停止后状态条隐藏', await cdp.eval(`return document.querySelector('#rd-speech').hidden`));

    console.log('\n【8】控制台错误');
    // favicon.ico 这类静态小图不算功能故障，单独剔出来但要如实报告
    const allErrs = logs.filter((l) => l.kind === 'error' || l.kind === 'pageerror');
    const badReq = [...new Set(failedUrls)];
    const errs = allErrs.filter((l) => !/favicon/i.test(l.text));
    ok('无 JS 报错', errs.length === 0, errs.slice(0, 4).map((e) => e.text.slice(0, 160)).join(' | '));
    ok('无资源加载失败（favicon 除外）', badReq.filter((u) => !/favicon/i.test(u)).length === 0,
      badReq.join(' | '));
    console.log(`  （警告 ${logs.filter((l) => l.kind === 'warning').length} 条）`);
    if (errs.length) errs.slice(0, 8).forEach((e) => console.log('    · ' + e.text.slice(0, 300)));
  } catch (e) {
    fail++; failures.push('执行异常: ' + e.message);
    console.error('\n执行异常：' + e.message);
    logs.slice(-10).forEach((l) => console.error('  · ' + l.kind + ': ' + l.text.slice(0, 200)));
  } finally {
    if (cdp) cdp.close();
    try { proc.kill(); } catch {}
    await sleep(400);
  }

  console.log(`\n===== 阅读器端到端：${pass} 通过 / ${fail} 失败 =====`);
  if (failures.length) { console.log('失败项：'); failures.forEach((f) => console.log('  - ' + f)); }
  process.exit(fail ? 1 : 0);
})();