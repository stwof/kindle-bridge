/* Kindle 桥 前端 */
(() => {
  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  };
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtSize = (n) => {
    if (!n) return '—';
    const u = ['B', 'KB', 'MB', 'GB'];
    let i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
  };
  const fmtDur = (s) => {
    if (!s || s <= 0) return '';
    if (s < 60) return Math.round(s) + ' 秒';
    if (s < 3600) return Math.round(s / 60) + ' 分钟';
    return (s / 3600).toFixed(1) + ' 小时';
  };
  const TYPE_CN = { highlight: '标注', note: '笔记', bookmark: '书签' };

  let DATA = null;
  let selected = new Set();

  function toast(msg, ms = 2600) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove('show'), ms);
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res;
  }

  async function download(kind) {
    try {
      const res = await api('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind }),
      });
      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const m = /filename\*=UTF-8''([^;]+)/.exec(cd);
      const name = m ? decodeURIComponent(m[1]) : 'kindle-export';
      const url = URL.createObjectURL(blob);
      const a = el('a');
      a.href = url; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      toast(`已导出：${name}`);
    } catch (e) {
      toast('导出失败：' + e.message);
    }
  }

  /* ---------- 渲染 ---------- */
  function renderDevice() {
    const dev = DATA.device;
    const box = $('#devbox');
    const dot = box.querySelector('.dot');
    const txt = $('#devtext');
    if (!dev) {
      dot.className = 'dot bad';
      txt.textContent = '未检测到 Kindle，请用数据线连接后点刷新';
      return;
    }
    dot.className = 'dot ok';
    const used = fmtSize(dev.used_bytes);
    const total = fmtSize(dev.total_bytes);
    txt.textContent = `${dev.name} · ${dev.root} · ${dev.version || '固件未知'} · ${used}/${total}`;
  }

  function renderStats() {
    const s = $('#stats');
    s.innerHTML = '';
    const dev = DATA.device || {};
    const lib = DATA.library || { books: [], orphans: [] };
    const hl = DATA.highlights?.stats || { total: 0, books: 0 };
    const vo = DATA.vocab?.stats || { total: 0, zh: 0, en: 0, lookups: 0 };
    const ready = lib.books.filter((b) => b.wechat_ready).length;

    const items = [
      ['设备内书籍', `${lib.books.length}<small>本</small>`],
      ['可直接导入微信读书', `${ready}<small>本</small>`],
      ['标注 / 笔记', `${hl.total}<small>条</small>`],
      ['生词本', `${vo.total}<small>词（中 ${vo.zh} / 英 ${vo.en}）</small>`],
      ['查词次数', `${vo.lookups}<small>次</small>`],
    ];
    for (const [k, v] of items) {
      const c = el('div', 'stat');
      c.appendChild(el('div', 'k', k));
      c.appendChild(el('div', 'v', v));
      s.appendChild(c);
    }
  }

  function renderLibrary() {
    const lib = DATA.library || { books: [], orphans: [] };
    const tb = $('#libtable tbody');
    tb.innerHTML = '';

    const ready = lib.books.filter((b) => b.wechat_ready).length;
    const drm = lib.books.filter((b) => b.drm === 'drm').length;
    $('#libhint').innerHTML = `共 ${lib.books.length} 本，其中 <b>${ready} 本</b> 可直接导入微信读书` +
      (drm ? `，<b>${drm} 本</b> 带 DRM（本工具不做破解）` : '') + '。' +
      (lib.orphans.length ? ` 另有 ${lib.orphans.length} 本已删除（仅剩阅读记录）。` : '');

    const calibre = !!DATA.calibre;
    $('#conv-wechat').hidden = !calibre;

    if (!lib.books.length) {
      tb.appendChild(el('tr', null, `<td colspan="7"><div class="empty">没有扫描到书籍文件</div></td>`));
      return;
    }

    for (const b of lib.books) {
      const tr = el('tr');

      const tdSel = el('td', 'c-sel');
      const cb = el('input');
      cb.type = 'checkbox';
      cb.checked = selected.has(b.file);
      cb.addEventListener('change', () => {
        cb.checked ? selected.add(b.file) : selected.delete(b.file);
      });
      tdSel.appendChild(cb);
      tr.appendChild(tdSel);

      const tdTitle = el('td', 'title-cell');
      tdTitle.innerHTML = `<b>${esc(b.title)}</b><div class="path">${esc(b.file)}</div>`;
      tr.appendChild(tdTitle);

      tr.appendChild(el('td', null, esc(b.author || '—')));
      tr.appendChild(el('td', null, `<span class="badge plain mono">${esc(b.ext)}</span>`));

      tr.appendChild(el('td', 'num', fmtSize(b.size)));
      tr.appendChild(el('td', 'num', esc(b.last_read || b.modified || '—')));

      const tdW = el('td');
      let cls = b.wechat_ready ? (b.ext === 'pdf' ? 'warn' : 'ok') : 'bad';
      let label = b.wechat_ready ? (b.ext === 'pdf' ? '可导入（体验一般）' : '可直接导入') : '需转换 / 不支持';
      tdW.innerHTML = `<span class="badge ${cls}" title="${esc(b.wechat_note)}">${label}</span>`;
      if (b.drm === 'drm') {
        tdW.innerHTML += ` <span class="badge bad" title="检测到 DRM，本工具不做任何破解">DRM</span>`;
      }
      tr.appendChild(tdW);

      tb.appendChild(tr);
    }
  }

  function renderHighlights() {
    const hl = DATA.highlights || { groups: [], stats: {} };
    const t = hl.stats.types || {};
    $('#hintips').innerHTML = `共 ${hl.stats.total || 0} 条（标注 ${t.highlight || 0} · 笔记 ${t.note || 0} · 书签 ${t.bookmark || 0}），来自 ${hl.stats.books || 0} 本书。`;
    renderHlList('');
  }

  function renderHlList(q) {
    const wrap = $('#hl-list');
    wrap.innerHTML = '';
    const groups = (DATA.highlights?.groups || []);
    const needle = q.trim().toLowerCase();
    let shown = 0;

    for (const g of groups) {
      const items = g.items.filter((it) => !needle || (it.text || '').toLowerCase().includes(needle));
      if (!items.length) continue;
      shown++;

      const block = el('div', 'book-block');
      const head = el('div', 'book-head');
      head.innerHTML = `<span class="chev">▶</span>
        <h3>${esc(g.title)} <span class="au">${esc(g.author || '')}</span></h3>
        <span class="badge plain">${items.length} 条</span>`;
      const body = el('div', 'book-body');

      for (const it of items) {
        const c = el('div', `clip ${it.type}`);
        const meta = [
          TYPE_CN[it.type] || '标注',
          it.page ? `第 ${it.page} 页` : '',
          it.location ? `位置 ${it.location}` : '',
          it.added_at || '',
        ].filter(Boolean).join(' · ');
        c.appendChild(el('div', 'txt', esc(it.text || '（无内容）')));
        c.appendChild(el('div', 'meta', esc(meta)));
        body.appendChild(c);
      }

      head.addEventListener('click', () => {
        block.classList.toggle('open');
        head.querySelector('.chev').textContent = block.classList.contains('open') ? '▼' : '▶';
      });
      block.appendChild(head);
      block.appendChild(body);
      wrap.appendChild(block);
    }

    if (!shown) {
      wrap.appendChild(el('div', 'empty', needle ? '没有匹配的标注' : '还没有标注记录'));
    }
  }

  function renderVocab() {
    const v = DATA.vocab || { words: [], stats: {} };
    $('#vhint').innerHTML = `共 <b>${v.stats.total || 0}</b> 个生词（中文 ${v.stats.zh || 0} · 英文 ${v.stats.en || 0}），累计查词 ${v.stats.lookups || 0} 次。`;
    renderVocabRows();
  }

  function renderVocabRows() {
    const tb = $('#vtable tbody');
    tb.innerHTML = '';
    const lang = $('#v-lang').value;
    const q = $('#v-search').value.trim().toLowerCase();
    const words = (DATA.vocab?.words || []).filter((w) =>
      (!lang || w.lang === lang) && (!q || w.word.toLowerCase().includes(q)));

    if (!words.length) {
      tb.appendChild(el('tr', null, `<td colspan="5"><div class="empty">没有匹配的生词</div></td>`));
      return;
    }
    for (const w of words.slice(0, 500)) {
      const tr = el('tr');
      tr.appendChild(el('td', 'mono', esc(w.word)));
      tr.appendChild(el('td', null, `<span class="badge plain">${w.lang === 'zh' ? '中文' : '英文'}</span>`));
      tr.appendChild(el('td', 'num', w.lookups || '—'));
      tr.appendChild(el('td', 'num', esc(w.last_lookup || w.added_at || '—')));
      const ctx = (w.contexts || [])[0];
      const cell = el('td');
      if (ctx) {
        cell.innerHTML = `${esc(ctx.text)}` + (ctx.book ? `<div class="path" style="font-size:11.5px;color:var(--faint)">《${esc(ctx.book)}》</div>` : '');
      } else cell.textContent = '—';
      tr.appendChild(cell);
      tb.appendChild(tr);
    }
    if (words.length > 500) {
      tb.appendChild(el('tr', null, `<td colspan="5"><div class="empty">仅显示前 500 条，导出可获取全部</div></td>`));
    }
  }

  const EXPORTS = [
    ['weread-txt', '微信读书笔记（txt）', '纯文本摘录，可整段粘贴到微信读书「想法」或任意笔记软件。'],
    ['highlights-md', '标注 Markdown（zip）', '每本书一个 .md，外加总索引，适合 Obsidian / Notion。'],
    ['highlights-csv', '标注表格（csv）', 'Excel / Numbers 可直接打开，含页码、位置、时间。'],
    ['highlights-json', '标注数据（json）', '结构化数据，便于自己写脚本二次处理。'],
    ['vocab-anki', '生词 · Anki 词库', '制表符分隔，含例句与出处，可直接导入 Anki。'],
    ['vocab-csv', '生词 · 表格（csv）', '含查询次数、最近查询、例句与出处。'],
    ['all', '全部打包（zip）', '上面所有格式一次性导出。'],
  ];

  function renderExport() {
    const box = $('#export-cards');
    box.innerHTML = '';
    for (const [kind, title, desc] of EXPORTS) {
      const card = el('div', 'card');
      card.appendChild(el('h3', null, title));
      card.appendChild(el('p', null, desc));
      const btn = el('button', 'primary go', kind === 'all' ? '打包下载' : '下载');
      btn.addEventListener('click', () => download(kind));
      card.appendChild(btn);
      box.appendChild(card);
    }
  }

  async function exportBooks(mode) {
    const files = [...selected];
    if (!files.length) return toast('请先在书库里勾选书籍');
    const target = $('#conv-wechat').dataset.target || 'azw3';
    const btn = mode === 'convert' ? $('#conv-wechat') : $('#copy-wechat');
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = mode === 'convert' ? '转换中…' : '复制中…';
    try {
      const res = await api('/api/books/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files, mode, target }),
      });
      const data = await res.json();
      renderBookResult(data, mode);
      const ok = data.results.filter((r) => r.ok).length;
      toast(`完成：成功 ${ok} / ${data.results.length}`);
    } catch (e) {
      toast('操作失败：' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  }

  function renderBookResult(data, mode) {
    const box = $('#libresult');
    box.innerHTML = '';
    const r = el('div', 'result');
    r.appendChild(el('div', 'row', `<b>输出目录：</b><span class="f mono">${esc(data.out_dir)}</span>`));
    for (const item of data.results) {
      const cls = item.ok ? 'ok' : 'bad';
      const tag = item.ok ? '成功' : '跳过';
      r.appendChild(el('div', 'row',
        `<span class="badge ${cls}">${tag}</span><span class="f">${esc(item.file)}</span><span style="color:var(--muted)">${esc(item.message)}</span>`));
    }
    const openBtn = el('button', 'ghost', '打开输出文件夹');
    openBtn.style.marginTop = '8px';
    openBtn.addEventListener('click', async () => {
      await api('/api/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: data.out_dir }),
      });
    });
    r.appendChild(openBtn);
    box.appendChild(r);
  }

  /* ---------- 书籍投递 ---------- */
  const ROUTES = [
    ['D', 'MOBI 家族 · 直拷，零转换', '首选',
      'Kindle 原生就读 .mobi / .azw / .azw3 / .prc。拷进 documents/ 就出现在书库里，能查词能标注 —— 不用转换，不用装任何东西。'],
    ['A', 'EPUB 离线转码', '推荐',
      'EPUB 设备读不了（固件里没有它的渲染器），需用 Calibre 转成 AZW3 再拷进 Kindle。不联网、不碰亚马逊账号，排版可控。'],
    ['B', '云端转码 · 免安装', '',
      '走亚马逊官方的 Send to Kindle：它接收 EPUB 并自动转码送到设备。零安装，但要用 @kindle.com 地址、需要联网。只收 EPUB。'],
    ['C', '原生阅读 · 留给 KOReader', '',
      'EPUB 原样整理好。等设备越狱装上 KOReader 后由它原生渲染，排版与 PDF 重排都是最好的。'],
  ];

  let ESTATE = null;
  let EFILES = [];
  let EREPORTS = {};
  const esel = new Set();

  const b64u = (str) => {
    const bytes = new TextEncoder().encode(str);
    let bin = '';
    for (const b of bytes) bin += String.fromCharCode(b);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  };

  function renderEpubRoutes() {
    const box = $('#epub-routes');
    box.innerHTML = '';
    for (const [k, title, badge, desc] of ROUTES) {
      const c = el('div', 'route' + (badge ? ' best' : ''));
      c.appendChild(el('div', 'rk', '路线 ' + k));
      if (badge) c.appendChild(el('span', 'tag badge ok', badge));
      c.appendChild(el('h3', null, title));
      c.appendChild(el('p', null, desc));
      box.appendChild(c);
    }
  }

  function renderEpubHint() {
    const st = ESTATE || {};
    const n = EFILES.length;
    const nEpub = EFILES.filter((f) => /\.epub$/i.test(f.name)).length;
    const nMobi = n - nEpub;
    const cal = st.calibre_ok
      ? `Calibre${st.calibre_version ? ' ' + esc(st.calibre_version) : ''} 已就绪`
      : '路线 A 需要 Calibre —— 见上方「路线 A 环境」卡片，可一键取回官方安装包';
    const dev = st.device_ok ? 'Kindle 已连接，可直接拷进 documents/' : '未连接 Kindle，处理好后手动拷入设备即可';
    const inv = n
      ? `「收书」里有 <b>${n}</b> 个文件` +
        (nMobi ? `（EPUB ${nEpub} · MOBI 家族 ${nMobi}）` : '') + '。'
      : '「收书」里还没有文件 —— 把 EPUB 或 MOBI 拖进来。';
    $('#epub-hint').innerHTML = `${inv} ${cal}；${dev}。`;
    $('#epub-azw3').disabled = !st.calibre_ok || !nEpub;
    $('#epub-native').disabled = !nMobi;
    $('#epub-push').disabled = !st.device_ok;
  }

  function renderEpubTable() {
    const tb = $('#epub-table tbody');
    tb.innerHTML = '';
    for (const n of [...esel]) if (!EFILES.some((f) => f.name === n)) esel.delete(n);
    renderEpubHint();

    if (!EFILES.length) {
      tb.appendChild(el('tr', null,
        '<td colspan="7"><div class="empty">把 EPUB 或 MOBI 拖进上面的虚线框，或点「选择文件」</div></td>'));
      return;
    }

    for (const f of EFILES) {
      const r = EREPORTS[f.name] || {};
      const tr = el('tr');

      const tdSel = el('td', 'c-sel');
      const cb = el('input');
      cb.type = 'checkbox';
      cb.checked = esel.has(f.name);
      cb.addEventListener('change', () => {
        cb.checked ? esel.add(f.name) : esel.delete(f.name);
      });
      tdSel.appendChild(cb);
      tr.appendChild(tdSel);

      tr.appendChild(el('td', 'title-cell', `<b>${esc(f.name)}</b><div class="path">${esc(f.modified || '')}</div>`));
      tr.appendChild(el('td', 'num', fmtSize(f.size)));
      const isMobi = r.kind === 'mobi';
      const fmt = isMobi ? (r.format || 'MOBI 家族') : ('EPUB ' + (r.version || '?'));
      tr.appendChild(el('td', null, `<span class="badge plain mono">${esc(fmt)}</span>`));
      tr.appendChild(el('td', null,
        `${esc(r.title || '—')}<div class="path">${esc(r.author || '未知作者')}</div>`));

      const st = [];
      if (r.drm) st.push('<span class="badge bad">DRM</span>');
      else if (r.valid === false) st.push('<span class="badge bad">结构有问题</span>');
      else if (r.valid) st.push('<span class="badge ok">结构合规</span>');
      if (r.fixed_layout) st.push('<span class="badge warn">固定版式</span>');
      if ((r.warnings || []).length) st.push(`<span class="badge warn">${r.warnings.length} 项提示</span>`);
      tr.appendChild(el('td', null, st.join(' ') || '<span class="badge plain">—</span>'));

      if (isMobi) {
        const g = [];
        if (r.kindle_native) g.push('<span class="badge ok">Kindle 原生可读</span>');
        if (r.kindle_ready) g.push('<span class="badge info">可传微信读书</span>');
        else if (!r.drm) g.push('<span class="badge warn">微信读书不收</span>');
        tr.appendChild(el('td', null, g.join(' ') || '<span class="badge plain">—</span>'));
      } else {
        tr.appendChild(el('td', null,
          `<span class="badge plain">${r.spine || 0} 章</span> ` +
          `<span class="badge plain">${r.images || 0} 图</span>` +
          (r.cover ? '' : ' <span class="badge warn">无封面</span>')));
      }

      tr.style.cursor = 'pointer';
      tr.addEventListener('click', (ev) => {
        if (ev.target.tagName === 'INPUT') return;
        showEpubDetail(f.name);
      });
      tb.appendChild(tr);
    }
  }

  function showEpubDetail(name) {
    const r = EREPORTS[name];
    const box = $('#epub-detail');
    box.innerHTML = '';
    if (!r) return;

    const d = el('div', 'rep');
    d.appendChild(el('h4', null, `体检报告 · ${esc(r.name)}`));

    const grid = el('div', 'meta-grid');
    const fields = r.kind === 'mobi' ? [
      ['格式', r.format || '—'],
      ['格式说明', r.format_detail || '—'],
      ['书名', r.title || '（缺失）'],
      ['作者', r.author || '（缺失）'],
      ['语言', r.language || '（缺失）'],
      ['压缩 / 编码', `${r.compression || '—'} / ${r.encoding || '—'}`],
      ['内部记录数', String(r.records ?? '—')],
      ['封面', r.cover ? '有' : '无'],
      ['Kindle 直接可读', r.kindle_native ? '是' : '否'],
      ['结论', r.drm ? '含 DRM，只能在这台设备上读'
        : (r.valid ? '拷进 documents/ 即可阅读，无需转换' : '文件本身有问题，见下方')],
    ] : [
      ['EPUB 版本', r.version || '—'],
      ['书名', r.title || '（缺失）'],
      ['作者', r.author || '（缺失）'],
      ['语言', r.language || '（缺失）'],
      ['正文顺序', `${r.spine || 0} 章`],
      ['图 / 样式 / 字体', `${r.images || 0} / ${r.css || 0} / ${r.fonts || 0}`],
      ['目录', r.nav ? '有' : '无'],
      ['封面', r.cover ? '有' : '无'],
      ['结论', r.drm ? '含 DRM，无法投递' : (r.valid ? '可以投递' : '结构需修复')],
    ];
    for (const [k, v] of fields) {
      const s = el('div');
      s.innerHTML = `${esc(k)}：<b>${esc(v)}</b>`;
      grid.appendChild(s);
    }
    d.appendChild(grid);

    const section = (title, color, list) => {
      if (!list || !list.length) return;
      d.appendChild(el('div', null, `<b style="color:${color}">${title}</b>`));
      const ul = el('ul');
      for (const it of list) {
        const msg = typeof it === 'string' ? it : it.msg;
        const fix = typeof it === 'string' ? '' : it.fix;
        ul.appendChild(el('li', null, esc(msg) + (fix ? ` <span class="fix">→ ${esc(fix)}</span>` : '')));
      }
      d.appendChild(ul);
    };
    section('必须处理', 'var(--red)', r.issues);
    section('建议注意', 'var(--amber)', r.warnings);
    section('说明', 'var(--muted)', r.notes);

    const btn = el('button', 'ghost', '收起');
    btn.addEventListener('click', () => { box.innerHTML = ''; });
    d.appendChild(btn);
    box.appendChild(d);
  }

  async function epubLoad() {
    try {
      ESTATE = await (await fetch('/api/epub/state')).json();
      const ib = await (await fetch('/api/epub/inbox')).json();
      EFILES = ib.files || [];
      EREPORTS = {};
      if (EFILES.length) {
        const res = await api('/api/epub/inspect', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        const d = await res.json();
        for (const r of d.reports || []) EREPORTS[r.name] = r;
      }
      $('#epub-detail').innerHTML = '';
      renderEpubTable();
    } catch (e) {
      toast('读取「收书」失败：' + e.message);
    }
  }

  async function epubUpload(files) {
    let ok = 0;
    for (const f of files) {
      if (!/\.(epub|mobi|azw3?|prc)$/i.test(f.name)) { toast('跳过不支持的格式：' + f.name); continue; }
      try {
        const res = await api('/api/epub/upload', {
          method: 'POST', headers: { 'X-Filename': b64u(f.name) }, body: f,
        });
        const d = await res.json();
        if (d.ok) ok++; else toast('上传失败：' + (d.error || f.name));
      } catch (e) {
        toast('上传失败：' + e.message);
      }
    }
    if (ok) toast(`已收入 ${ok} 个文件`);
    await epubLoad();
  }

  // 简繁转换：上传 → 转换 → 直接下载；可选同时落「收书」
  async function zhConvert(files) {
    const dir = $('#zh-dir').value;
    const inbox = $('#zh-inbox').checked ? '1' : '0';
    const box = $('#zh-result');
    box.innerHTML = '';
    let done = 0;
    for (const f of files) {
      if (!/\.(epub|txt|text|md|csv)$/i.test(f.name)) { toast('跳过不支持的格式：' + f.name); continue; }
      const row = el('div', 'zh-item');
      row.textContent = `转换中：${f.name} …`;
      box.appendChild(row);
      try {
        const res = await api('/api/zh-convert', {
          method: 'POST',
          headers: { 'X-Filename': b64u(f.name), 'X-Direction': dir, 'X-Inbox': inbox },
          body: f,
        });
        const blob = await res.blob();
        const cd = res.headers.get('Content-Disposition') || '';
        const m = /filename\*=UTF-8''([^;]+)/.exec(cd);
        const name = m ? decodeURIComponent(m[1]) : f.name;
        const url = URL.createObjectURL(blob);
        const a = el('a');
        a.href = url; a.download = name;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);

        let meta = {};
        try { meta = JSON.parse(atob(res.headers.get('X-Zh-Meta') || 'e30=')); } catch (e) { /* ignore */ }
        const bits = [];
        if (meta.direction) bits.push('方向：' + meta.direction);
        if (meta.encoding) bits.push('编码：' + meta.encoding);
        if (meta.changed === false && !meta.skipped) bits.push('（已是目标字体，未改动）');
        if (meta.skipped) bits.push('未处理：' + (meta.reason || ''));
        if (meta.inbox) bits.push('已入收书：' + meta.inbox);
        if (Array.isArray(meta.converted)) bits.push('改动文件：' + meta.converted.length + ' 个');
        if (meta.title_after && meta.title_before && meta.title_after !== meta.title_before)
          bits.push(`书名：${meta.title_before} → ${meta.title_after}`);
        if (meta.error) bits.push('⚠ ' + meta.error);
        row.innerHTML = '';
        row.appendChild(el('div', 'zh-name', '✓ ' + name));
        row.appendChild(el('div', 'zh-meta', bits.join(' · ')));
        done++;
      } catch (e) {
        row.innerHTML = '';
        row.appendChild(el('div', 'zh-name err', '✗ ' + f.name));
        row.appendChild(el('div', 'zh-meta', '失败：' + e.message));
      }
    }
    if (done) toast(`已转换并下载 ${done} 个文件`);
  }

  function epubSelection() {
    return esel.size ? [...esel] : EFILES.map((f) => f.name);
  }

  async function epubPrepare(mode) {
    const files = epubSelection();
    if (!files.length) return toast('「收书」里没有文件');
    const sel = { azw3: '#epub-azw3', native: '#epub-native', koreader: '#epub-koreader' }[mode];
    const btn = $(sel || '#epub-azw3');
    btn.disabled = true;
    try {
      const res = await api('/api/epub/prepare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files, mode, push: $('#epub-push').checked }),
      });
      const d = await res.json();
      renderEpubResult(d);
      const ok = (d.results || []).filter((r) => r.ok).length;
      toast(`完成：成功 ${ok} / ${(d.results || []).length}`);
    } catch (e) {
      toast('处理失败：' + e.message);
    } finally {
      btn.disabled = false;
      renderEpubHint();
    }
  }

  async function epubMakeEml() {
    const files = epubSelection();
    if (!files.length) return toast('「收书」里没有文件');
    const to = $('#epub-to').value.trim();
    const from = $('#epub-from').value.trim();
    const rows = [];
    let outDir = '';
    for (const name of files) {
      try {
        const res = await api('/api/epub/eml', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file: name, to, from }),
        });
        const d = await res.json();
        if (d.ok) {
          rows.push({ file: name, ok: true, message: d.note || '', out: d.out });
          outDir = d.out.replace(/[\\/][^\\/]+$/, '');
        } else rows.push({ file: name, ok: false, message: d.error || '失败' });
      } catch (e) {
        rows.push({ file: name, ok: false, message: e.message });
      }
    }
    renderEpubResult({ out_dir: outDir, results: rows, pushed: [] });
    toast('邮件已生成，去「导出 / SendToKindle」双击打开');
  }

  async function epubRemove() {
    const files = [...esel];
    if (!files.length) return toast('先勾选要移除的文件');
    try {
      await api('/api/epub/remove', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files }),
      });
      esel.clear();
      toast(`已从「收书」移除 ${files.length} 个文件`);
      await epubLoad();
    } catch (e) {
      toast('移除失败：' + e.message);
    }
  }

  function renderEpubResult(d) {
    const box = $('#epub-result');
    box.innerHTML = '';
    const r = el('div', 'result');
    if (d.out_dir) {
      const label = d.mode === 'native' ? '目标位置' : '输出目录';
      r.appendChild(el('div', 'row', `<b>${label}：</b><span class="f mono">${esc(d.out_dir)}</span>`));
    }
    for (const item of d.results || []) {
      // 重复跳过算成功，但得让人一眼看出「没拷，是因为已经有了」
      const dup = /已经有这本了/.test(item.message || '');
      const tag = item.ok ? (dup ? '已在设备' : '成功') : '跳过';
      const cls = item.ok ? (dup ? 'info' : 'ok') : 'bad';
      r.appendChild(el('div', 'row',
        `<span class="badge ${cls}">${tag}</span>` +
        `<span class="f">${esc(item.file)}</span>` +
        `<span style="color:var(--muted)">${esc(item.message)}</span>`));
    }
    for (const item of d.pushed || []) {
      r.appendChild(el('div', 'row',
        `<span class="badge ${item.ok ? 'info' : 'bad'}">${item.ok ? '已入设备' : '未入设备'}</span>` +
        `<span class="f">${esc(item.out_name || item.file)}</span>` +
        `<span style="color:var(--muted)">${esc(item.message)}</span>`));
    }
    if (d.out_dir) {
      const openBtn = el('button', 'ghost', '打开输出文件夹');
      openBtn.style.marginTop = '8px';
      openBtn.addEventListener('click', () => api('/api/open', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: d.out_dir }),
      }));
      r.appendChild(openBtn);
    }
    box.appendChild(r);
  }

  /* ---------- 设备重复书体检（只读） ---------- */
  function renderDupes(d) {
    const box = $('#epub-result');
    box.innerHTML = '';
    const r = el('div', 'result');

    if (!d.ok) {
      r.appendChild(el('div', 'row',
        '<span class="badge bad">未连接</span>没有检测到 Kindle，扫不了。连上设备再试。'));
      box.appendChild(r);
      return;
    }
    if (!d.groups || !d.groups.length) {
      r.appendChild(el('div', 'row',
        `<span class="badge ok">干净</span>扫了 <b>${d.scanned}</b> 本书，`
        + '没有发现内容完全相同的重复文件。'));
      box.appendChild(r);
      return;
    }

    r.appendChild(el('div', 'row',
      `<span class="badge bad">发现重复</span>扫了 <b>${d.scanned}</b> 本书，`
      + `有 <b>${d.groups.length}</b> 组内容完全相同，多占约 <b>${esc(d.wasted_text)}</b>。`
      + '<span style="color:var(--muted)">下面每组留一份就够，其余可自行删除。</span>'));
    for (const g of d.groups) {
      const files = (g.files || []).map((f) => `<div class="mono" style="padding-left:14px">${esc(f)}</div>`).join('');
      r.appendChild(el('div', 'row',
        `<div><span class="badge bad">${esc(fmtSize(g.waste))}</span>` +
        `<span style="color:var(--muted)">${g.files.length} 份相同</span></div>${files}`));
    }
    box.appendChild(r);
  }

  async function epubDupes() {
    const btn = $('#epub-dupes');
    const old = btn.textContent;
    btn.disabled = true;
    btn.textContent = '扫描中…';
    try {
      renderDupes(await (await api('/api/device/dupes')).json());
    } catch (e) {
      toast('扫描失败：' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  }

  /* ---------- 路线 A 环境 · Calibre ---------- */
  let CAL = null;          // /api/calibre/state 的返回
  let CALPOLL = null;      // 下载进度轮询
  let CAL_ARM = false;     // 「运行安装向导」的两段式确认

  const mkBtn = (label, cls, fn, disabled) => {
    const b = el('button', cls, esc(label));
    if (disabled) b.disabled = true;
    b.addEventListener('click', fn);
    return b;
  };

  const mkLink = (label, href, fn) => {
    const a = el('a', 'env-link', esc(label));
    if (href) { a.href = href; a.target = '_blank'; a.rel = 'noreferrer'; }
    if (fn) a.addEventListener('click', (e) => { e.preventDefault(); fn(); });
    return a;
  };

  function mkStep(n, title, desc) {
    const s = el('div', 'step');
    s.appendChild(el('div', 'step-n', String(n)));
    const b = el('div', 'step-b');
    b.appendChild(el('div', 'step-t', esc(title)));
    if (desc) b.appendChild(el('div', 'step-d', desc));
    s.appendChild(b);
    return s;
  }

  function renderCalibre() {
    const box = $('#cal-body');
    const state = $('#cal-state');
    if (!CAL) {
      state.className = 'env-state';
      state.textContent = '检测中…';
      box.innerHTML = '';
      return;
    }
    const st = CAL.calibre || {};
    const inst = CAL.installer || {};
    const pr = CAL.progress || {};
    box.innerHTML = '';

    /* --- 已装好 --- */
    if (st.ok) {
      state.className = 'env-state ok';
      state.textContent = '已就绪' + (st.version ? ' · v' + st.version : '');
      const p = el('div', 'env-ok');
      p.innerHTML = `<b>Calibre ${esc(st.version || '')}</b> 已安装，路线 A 可以用了。` +
        `<div class="env-path mono">${esc(st.path)}</div>`;
      box.appendChild(p);
      const bar = el('div', 'env-actions');
      bar.appendChild(mkBtn('重新检测', 'ghost', () => calibreRedetect(true)));
      box.appendChild(bar);
      return;
    }

    /* --- 未装好：三步引导 --- */
    state.className = 'env-state bad';
    state.textContent = pr.active ? '正在下载安装包…'
      : pr.phase === 'cancelled' ? '下载已暂停，可继续'
      : (inst.ready ? '安装包就绪，等你安装' : '未安装');

    const steps = el('div', 'steps');

    // ① 取回安装包
    const s1 = mkStep(1, '取回官方安装包', '从 calibre-ebook.com 分段下载，支持断点续传，随时可停。');
    const c1 = el('div', 'step-ctl');
    const partial = (CAL.partial && CAL.partial.bytes) || 0;
    if (pr.active) {
      const pct = pr.total ? Math.min(100, (pr.downloaded / pr.total) * 100) : 0;
      const wrap = el('div', 'prog');
      const phaseCn = { resolving: '正在解析最新版本…', downloading: '正在下载中',
                        merging: '下载完成，正在合并分片…' }[pr.phase] || '处理中…';
      let meta = phaseCn;
      if (pr.phase === 'merging') {
        meta = '正在合并分片并校验…';
      } else if (pr.total) {
        meta = `${fmtSize(pr.downloaded)} / ${fmtSize(pr.total)} · ${pct.toFixed(1)}%` +
          (pr.speed ? ` · ${fmtSize(pr.speed)}/s` : '') +
          (pr.eta ? ` · 约剩 ${fmtDur(pr.eta)}` : '') +
          (pr.segments > 1 ? ` · ${pr.segments} 路并发` : '');
      }
      wrap.innerHTML = `<div class="prog-track"><div class="prog-fill" style="width:${pct.toFixed(1)}%"></div></div>` +
        `<div class="prog-meta">${esc(meta)}</div>`;
      c1.appendChild(wrap);
      c1.appendChild(mkBtn('取消', 'ghost', () => calCancel()));
      if (pr.phase === 'downloading' && pr.speed && pr.speed < 100 * 1024) {
        c1.appendChild(el('div', 'env-note',
          '这条线是跨境线路，速度偏慢属正常。可以先去忙别的，中断了下次点「继续下载」会从断点接着走。'));
      }
    } else if (inst.ready) {
      c1.appendChild(el('span', null,
        `<span class="badge ok">已下载</span> <span class="mono">${esc(inst.name)}</span> · ${fmtSize(inst.size)} · ${esc(inst.modified)}`));
      c1.appendChild(mkBtn('重新下载', 'ghost', () => calDownload(true)));
    } else if (partial > 0) {
      c1.appendChild(el('span', null, `<span class="badge warn">上次未下完</span> 已下 ${fmtSize(partial)}`));
      c1.appendChild(mkBtn(`继续下载 · 约 ${fmtSize(228 * 1024 * 1024 - partial)} 剩余`, 'primary',
        () => calDownload(false)));
      c1.appendChild(mkLink('重新开始', null, () => calDownload(true)));
    } else {
      c1.appendChild(mkBtn('下载官方安装包 · 约 228 MB', 'primary', () => calDownload(false)));
      c1.appendChild(mkLink('或打开官网自行下载', CAL.official_page));
    }
    if (pr.phase === 'error' && pr.error) {
      c1.appendChild(el('div', 'env-err', '下载失败：' + esc(pr.error)));
    }
    if (pr.phase === 'cancelled' && pr.error) {
      c1.appendChild(el('div', 'env-note', esc(pr.error)));
    }
    s1.appendChild(c1);
    steps.appendChild(s1);

    // ② 运行安装向导
    const s2 = mkStep(2, '运行安装向导', '双击安装包走完向导即可，默认装到 C:\\Program Files\\Calibre2。');
    const c2 = el('div', 'step-ctl');
    if (CAL_ARM) {
      c2.appendChild(el('div', 'env-warn', '将启动 ' + esc(inst.name || '安装包') + '，Windows 会弹出安装向导。'));
      c2.appendChild(mkBtn('确认运行', 'primary', () => { CAL_ARM = false; calRun(); }));
      c2.appendChild(mkBtn('取消', 'ghost', () => { CAL_ARM = false; renderCalibre(); }));
    } else {
      c2.appendChild(mkBtn('运行安装向导', 'primary', () => { CAL_ARM = true; renderCalibre(); }, !inst.ready));
      c2.appendChild(mkBtn('打开所在文件夹', 'ghost', () => calReveal()));
      if (inst.sha256) {
        c2.appendChild(el('div', 'env-hash mono',
          'SHA-256 ' + esc(inst.sha256.slice(0, 40)) + '…'));
      }
    }
    s2.appendChild(c2);
    steps.appendChild(s2);

    // ③ 复检
    const s3 = mkStep(3, '回来点「重新检测」', '装好后本页立刻认出新版本，不用重启工具。');
    const c3 = el('div', 'step-ctl');
    c3.appendChild(mkBtn('重新检测', 'ghost', () => calibreRedetect(true)));
    c3.appendChild(mkLink('不想装软件？改用路线 B（下方）', null,
      () => $('#epub-sendbox').scrollIntoView({ behavior: 'smooth', block: 'center' })));
    s3.appendChild(c3);
    steps.appendChild(s3);

    box.appendChild(steps);

    const foot = el('div', 'env-foot',
      '下载来源被限定在官方域名（calibre-ebook.com / download.calibre-ebook.com / github.com），' +
      '落盘前校验体积、文件头魔数与 SHA-256。本工具不会静默安装，也不会改注册表或 PATH。');
    box.appendChild(foot);
  }

  async function calibreLoad(force) {
    try {
      CAL = await (await fetch('/api/calibre/state' + (force ? '?force=1' : ''))).json();
      renderCalibre();
    } catch (e) {
      toast('读取 Calibre 状态失败：' + e.message);
    }
  }

  async function calibreRedetect(force) {
    if (CALPOLL) return;
    toast('正在重新检测 Calibre…');
    await calibreLoad(force);
    await epubLoad();
    const st = (CAL && CAL.calibre) || {};
    toast(st.ok ? `已检测到 Calibre ${st.version || ''}` : '仍未检测到 Calibre', 3600);
  }

  function calPollStart() {
    if (CALPOLL) return;
    CALPOLL = setInterval(async () => {
      try {
        const p = await (await fetch('/api/calibre/progress')).json();
        if (CAL) CAL.progress = p;
        renderCalibre();
        if (!p.active) {
          clearInterval(CALPOLL);
          CALPOLL = null;
          await calibreLoad(true);
          const ok = (CAL && CAL.installer && CAL.installer.ready);
          toast(ok ? '安装包已就绪，点「运行安装向导」' : '下载结束，请查看状态', 5000);
        }
      } catch (e) { /* 单次轮询失败无所谓，下一次继续 */ }
    }, 600);
  }

  async function calDownload(force) {
    try {
      const res = await fetch('/api/calibre/download', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: !!force }),
      });
      const d = await res.json();
      if (!d.ok) return toast(d.error || '无法开始下载');
      if (CAL) CAL.progress = { active: true, phase: 'resolving', downloaded: 0, total: 0, speed: 0 };
      renderCalibre();
      toast('已开始下载官方安装包…');
      calPollStart();
    } catch (e) {
      toast('下载失败：' + e.message);
    }
  }

  async function calCancel() {
    try {
      const res = await fetch('/api/calibre/cancel', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      const d = await res.json();
      toast(d.ok ? (d.note || '正在停止…') : (d.error || '取消失败'), 6000);
    } catch (e) {
      toast('取消失败：' + e.message);
    }
  }

  async function calReveal() {
    try {
      const res = await fetch('/api/calibre/reveal', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      const d = await res.json();
      toast(d.ok ? (d.revealed ? '已在资源管理器中定位到安装包' : '已打开「工具」文件夹') : (d.error || '打开失败'));
    } catch (e) {
      toast('打开失败：' + e.message);
    }
  }

  async function calRun() {
    try {
      const res = await fetch('/api/calibre/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
      });
      const d = await res.json();
      toast(d.ok ? (d.note || '安装向导已打开') : (d.error || '启动失败'), d.ok ? 7000 : 4000);
    } catch (e) {
      toast('启动失败：' + e.message);
    } finally {
      renderCalibre();
    }
  }

  /* ---------- 公版书库 ---------- */
  const FREE = { q: '', source: 'all', lang: '', page: 1, data: null, poll: null, doneSeen: 0 };
  const FREE_CHIPS = [
    ['热门', '', ''],
    ['中文公版书', '', 'zh'],
    ['福尔摩斯', 'sherlock holmes', ''],
    ['凡尔纳', 'jules verne', ''],
    ['简·奥斯汀', 'austen', ''],
    ['狄更斯', 'dickens', ''],
    ['爱伦·坡', 'edgar allan poe', ''],
    ['童话', 'fairy tales', ''],
    ['哲学', 'philosophy', ''],
  ];

  // 没有封面时用书名首字配一个稳定的底色，比空框体面
  const hueOf = (s) => {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return h;
  };

  function renderFreeChips() {
    const box = $('#free-chips');
    box.innerHTML = '';
    for (const [label, q, lang] of FREE_CHIPS) {
      const on = FREE.q === q && FREE.lang === lang
        && (q || lang ? true : FREE.source === 'all');
      const c = el('span', 'chip' + (on ? ' on' : ''), esc(label));
      c.addEventListener('click', () => {
        FREE.q = q; FREE.lang = lang; FREE.source = 'all';
        $('#free-q').value = q;
        $('#free-lang').value = lang;
        $('#free-source').value = 'all';
        renderFreeChips();
        freeSearch(1);
      });
      box.appendChild(c);
    }
  }

  function freeCard(item) {
    const card = el('article', 'bk');
    const top = el('div', 'bk-top');

    const cov = el('div', 'bk-cover');
    const first = (item.title || '?').trim().charAt(0) || '?';
    if ($('#free-cover').checked && item.cover) {
      const img = el('img');
      img.loading = 'lazy';
      img.alt = '';
      img.src = item.cover;
      img.addEventListener('error', () => { cov.textContent = first; });
      cov.appendChild(img);
    } else {
      cov.textContent = first;
      const h = hueOf(item.title || '');
      cov.style.background = `hsl(${h} 34% 93%)`;
      cov.style.color = `hsl(${h} 30% 38%)`;
      cov.style.fontWeight = '500';
    }
    top.appendChild(cov);

    const meta = el('div', 'bk-meta');
    meta.appendChild(el('h4', null, esc(item.title)));
    meta.appendChild(el('div', 'bk-au', esc(item.author)));
    const tags = el('div', 'bk-tags');
    tags.appendChild(el('span', 'badge plain', esc(item.source_name)));
    if (item.langs && item.langs.length) {
      tags.appendChild(el('span', 'badge plain', esc(item.langs.slice(0, 2).join(' / '))));
    }
    // 本地中文经典没有下载量，works 是篇数，显示成「下载 N」会很怪
    if (item.source === 'classics') {
      if (item.downloads) {
        tags.appendChild(el('span', 'badge plain', `${item.downloads.toLocaleString()} 篇`));
      }
      for (const s of (item.subjects || [])) {
        if (s) tags.appendChild(el('span', 'badge plain', esc(s)));
      }
    } else if (item.downloads) {
      tags.appendChild(el('span', 'badge plain', `下载 ${item.downloads.toLocaleString()}`));
    }
    if (!item.files.length) {
      tags.appendChild(el('span', 'badge warn', '只有网页版'));
    }
    meta.appendChild(tags);
    top.appendChild(meta);
    card.appendChild(top);

    const files = el('div', 'bk-files');
    for (const f of item.files) {
      const row = el('div', 'bk-file');
      const btn = el('button', f.native ? 'primary' : 'ghost');
      btn.textContent = `取回 · ${f.label}`;
      if (!item.files.length) btn.disabled = true;
      btn.addEventListener('click', () => freeFetch(item, f, btn));
      row.appendChild(btn);
      row.appendChild(el('span', 'why', esc(f.note || '')));
      files.appendChild(row);
    }
    // 本地语料没有源站页面
    if (item.page_url) {
      const link = el('a', 'bk-link', '在源站查看这一本 ↗');
      link.href = item.page_url;
      link.target = '_blank';
      link.rel = 'noreferrer';
      files.appendChild(link);
    }
    card.appendChild(files);
    return card;
  }

  function renderFree() {
    const d = FREE.data;
    const box = $('#free-gridbox');
    const st = $('#free-state');
    box.innerHTML = '';
    if (!d) return;

    if (d.stale) st.className = 'env-state bad';
    else st.className = 'env-state ok';
    st.textContent = `命中 ${(d.items || []).length} 条 · 第 ${d.page} 页`
      + (d.count ? ` · 源站共 ${d.count} 条` : '')
      + (d.partial ? ' · 部分书源未返回' : '')
      + (d.errors && d.errors.length ? ` · ${d.errors.join('；')}` : '');

    if (d.hint) {
      const p = el('div', 'env-note', esc(d.hint));
      box.appendChild(p);
    }
    if (!d.items.length) {
      box.appendChild(el('div', 'empty', '没搜到。换个关键词，或点上面的「中文公版书 / 热门」看看有什么。'));
      return;
    }
    const grid = el('div', 'bk-grid');
    for (const it of d.items) grid.appendChild(freeCard(it));
    box.appendChild(grid);

    const pager = el('div', 'pager');
    const prev = el('button', 'ghost', '← 上一页');
    const next = el('button', 'ghost', '下一页 →');
    prev.disabled = d.page <= 1;
    next.disabled = (d.items || []).length < 20;
    prev.addEventListener('click', () => freeSearch(d.page - 1));
    next.addEventListener('click', () => freeSearch(d.page + 1));
    pager.appendChild(prev);
    pager.appendChild(el('span', null, `第 ${d.page} 页`));
    pager.appendChild(next);
    box.appendChild(pager);
  }

  async function freeSearch(page) {
    FREE.q = $('#free-q').value.trim();
    FREE.source = $('#free-source').value;
    FREE.lang = $('#free-lang').value;
    FREE.page = page || 1;
    renderFreeChips();
    const box = $('#free-gridbox');
    box.innerHTML = '<div class="empty">正在向书源取数…<br>'
      + '（正常 2~3 秒。若此刻正在下载大文件，跨境线路会被占满，最多等 25 秒先回一半结果）</div>';
    $('#free-state').className = 'env-state';
    $('#free-state').textContent = '检索中…';
    const qs = new URLSearchParams({
      q: FREE.q, source: FREE.source, lang: FREE.lang, page: String(FREE.page),
    });
    try {
      const res = await api('/api/free/search?' + qs.toString());
      FREE.data = await res.json();
      renderFree();
    } catch (e) {
      box.innerHTML = `<div class="empty">检索失败：${esc(e.message)}</div>`;
      $('#free-state').className = 'env-state bad';
      $('#free-state').textContent = '检索失败';
    }
  }

  async function freeFetch(item, file, btn) {
    btn.disabled = true;
    const push = $('#free-push').checked;
    try {
      // 本地中文经典不下载、不排队，直接在本地排书，几秒就好
      if (file.classic) {
        const res = await api('/api/classics/build', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_id: String(file.url || '').replace(/^classic:/, ''),
            push, target: file.ext === '.azw3' ? 'azw3' : 'epub',
            simplified: true,
          }),
        });
        const d = await res.json();
        if (d.error) throw new Error(d.error);
        toast(`已排好《${d.title}》：${d.chapters} 篇`
          + (d.push ? ` · ${d.push.message}` : ` · ${d.note || '已放入「收书」'}`));
        btn.disabled = false;
        return;
      }
      const res = await api('/api/free/fetch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          push,
          items: [{
            title: item.title, author: item.author, url: file.url,
            ext: file.ext, source_name: item.source_name,
            simplified: !!file.simplified,
          }],
        }),
      });
      const d = await res.json();
      if (d.error) throw new Error(d.error);
      toast(`已开始取回：${item.title}`);
      startFreePoll();
    } catch (e) {
      btn.disabled = false;
      toast('取回失败：' + e.message);
    }
  }

  function renderFreeQueue(st) {
    const box = $('#free-queue');
    box.innerHTML = '';
    const cur = st.current;
    if (cur) {
      const wrap = el('div', 'envcard');
      const head = el('div', 'env-head');
      head.appendChild(el('span', 'env-kicker', `正在取回 · ${esc(cur.source_name)}`));
      head.appendChild(el('span', 'env-state', `${cur.status} ${cur.percent || 0}%`));
      wrap.appendChild(head);
      wrap.appendChild(el('div', 'env-ok', esc(cur.title)));
      const prog = el('div', 'prog');
      prog.style.marginTop = '10px';
      const track = el('div', 'prog-track');
      const fill = el('div', 'prog-fill');
      fill.style.width = (cur.percent || 0) + '%';
      track.appendChild(fill);
      prog.appendChild(track);
      const mb = cur.total ? `${fmtSize(cur.got)} / ${fmtSize(cur.total)}` : fmtSize(cur.got);
      const sp = cur.speed_avg ? `${Math.round(cur.speed_avg / 1024)} KB/s` : '测速中';
      prog.appendChild(el('div', 'prog-meta',
        `${mb} · ${sp}${cur.eta ? ` · 约剩 ${fmtDur(cur.eta)}` : ''}`
        + (cur.segments ? ` · ${cur.segments} 路分片` : '')));
      wrap.appendChild(prog);
      const cancel = el('button', 'ghost', '取消');
      cancel.style.marginTop = '10px';
      cancel.addEventListener('click', async () => {
        await api('/api/free/cancel', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: cur.id }),
        });
        toast('已请求取消');
      });
      wrap.appendChild(cancel);
      box.appendChild(wrap);
    }

    const jobs = (st.jobs || []).filter((j) => j.status !== '排队');
    if (jobs.length) {
      const r = el('div', 'result');
      const head = el('div', 'row');
      head.innerHTML = `<b>取回记录</b><span class="f" style="color:var(--muted)">`
        + `完成 ${st.done} · 失败 ${st.failed} · 落盘位置 <span class="mono">${esc(st.inbox)}</span></span>`;
      r.appendChild(head);
      for (const j of jobs.slice(-8).reverse()) {
        const cls = j.status === '完成' ? 'ok' : (j.status === '失败' ? 'bad' : 'info');
        const extra = j.status === '完成'
          ? `${j.note || ''}${(j.pushed || []).length ? ' · ' + esc(j.pushed[0].message) : ''}`
          : (j.error || j.status);
        const row = el('div', 'row',
          `<span class="badge ${cls}">${esc(j.status)}</span>`
          + `<span class="f">${esc(j.title)}${j.out_name ? ` <span class="mono" style="color:var(--faint)">${esc(j.out_name)}</span>` : ''}</span>`
          + `<span style="color:var(--muted)">${esc(extra)}</span>`);
        if (j.status === '失败' || j.status === '已取消' || j.status === '自动重试排队') {
          const btn = el('button', 'ghost', j.status === '自动重试排队' ? '立即重试' : '重试');
          btn.style.marginLeft = '8px';
          btn.style.flexShrink = '0';
          btn.addEventListener('click', async () => {
            btn.disabled = true;
            await api('/api/free/retry', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: j.id }) });
            freePollOnce();
          });
          row.appendChild(btn);
        }
        r.appendChild(row);
      }
      if (st.failed > 0) {
        const retryAll = el('button', 'ghost', `重试全部失败（${st.failed}）`);
        retryAll.style.marginTop = '8px';
        retryAll.addEventListener('click', async () => {
          await api('/api/free/retry', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
          freePollOnce();
        });
        r.appendChild(retryAll);
      }
      const clear = el('button', 'ghost', '清空记录');
      clear.style.marginTop = '8px';
      clear.addEventListener('click', async () => {
        await api('/api/free/clear', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        freePollOnce();
      });
      const openBtn = el('button', 'ghost', '打开「收书」文件夹');
      openBtn.style.margin = '8px 0 0 8px';
      openBtn.addEventListener('click', () => api('/api/open', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: st.inbox }),
      }));
      r.appendChild(clear);
      r.appendChild(openBtn);
      box.appendChild(r);
    }
  }

  async function freePollOnce() {
    let st;
    try {
      st = await (await api('/api/free/state')).json();
    } catch (e) { return null; }
    renderFreeQueue(st);
    if (st.done > FREE.doneSeen) {
      FREE.doneSeen = st.done;
      epubLoad();                       // 「收书」多出文件了，书籍投递页同步跟上
    }
    return st;
  }

  function startFreePoll() {
    if (FREE.poll) return;
    const tick = async () => {
      const st = await freePollOnce();
      if (st && !st.busy) {
        clearInterval(FREE.poll);
        FREE.poll = null;
        toast('取回结束，去「书籍投递」把它拷进 Kindle 吧');
      }
    };
    FREE.poll = setInterval(tick, 900);
    tick();
  }

  /* ---------- 交互 ---------- */
  function bind() {
    document.querySelectorAll('.tab').forEach((t) => {
      t.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
        document.querySelectorAll('.panel').forEach((x) => x.classList.remove('active'));
        t.classList.add('active');
        $('#panel-' + t.dataset.tab).classList.add('active');
        if (t.dataset.tab === 'free') {
          freePollOnce();
          if (!FREE.data) freeSearch(1);
        }
      });
    });

    $('#refresh').addEventListener('click', () => load(true));
    $('#hl-search').addEventListener('input', (e) => renderHlList(e.target.value));
    $('#hl-expand').addEventListener('click', () => {
      const blocks = document.querySelectorAll('.book-block');
      const anyClosed = [...blocks].some((b) => !b.classList.contains('open'));
      blocks.forEach((b) => {
        b.classList.toggle('open', anyClosed);
        const c = b.querySelector('.chev');
        if (c) c.textContent = anyClosed ? '▼' : '▶';
      });
    });
    $('#v-lang').addEventListener('change', renderVocabRows);
    $('#v-search').addEventListener('input', renderVocabRows);

    $('#clear-sel').addEventListener('click', () => {
      selected.clear();
      document.querySelectorAll('#libtable input[type=checkbox]').forEach((c) => { c.checked = false; });
      toast('已清空选择');
    });
    $('#sel-nonwechat').addEventListener('click', () => {
      selected.clear();
      const rows = document.querySelectorAll('#libtable tbody tr');
      (DATA.library?.books || []).forEach((b, i) => {
        if (!b.wechat_ready) { selected.add(b.file); const cb = rows[i]?.querySelector('input'); if (cb) cb.checked = true; }
      });
      toast(`已选中 ${selected.size} 本需要转换的书`);
    });
    $('#copy-wechat').addEventListener('click', () => exportBooks('copy'));
    $('#conv-wechat').addEventListener('click', () => exportBooks('convert'));

    // 书籍投递
    const dz = $('#dropzone');
    ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.add('over');
    }));
    ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.remove('over');
    }));
    dz.addEventListener('drop', (e) => {
      const fl = e.dataTransfer && e.dataTransfer.files;
      if (fl && fl.length) epubUpload(fl);
    });
    $('#pick-epub').addEventListener('click', () => $('#epub-file').click());
    $('#epub-file').addEventListener('change', (e) => {
      if (e.target.files.length) epubUpload(e.target.files);
      e.target.value = '';
    });
    $('#epub-open-inbox').addEventListener('click', async () => {
      const p = ESTATE && ESTATE.inbox;
      if (!p) return;
      await api('/api/open', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: p }),
      });
    });
    $('#epub-rescan').addEventListener('click', epubLoad);
    $('#epub-dupes').addEventListener('click', epubDupes);
    $('#epub-remove').addEventListener('click', epubRemove);
    $('#epub-azw3').addEventListener('click', () => epubPrepare('azw3'));
    $('#epub-native').addEventListener('click', () => epubPrepare('native'));
    $('#epub-koreader').addEventListener('click', () => epubPrepare('koreader'));
    $('#epub-eml').addEventListener('click', epubMakeEml);
    $('#epub-web').addEventListener('click', () => window.open('https://www.amazon.com/sendtokindle', '_blank', 'noopener'));

    // 简繁转换
    const zdz = $('#zh-dropzone');
    ['dragenter', 'dragover'].forEach((ev) => zdz.addEventListener(ev, (e) => {
      e.preventDefault();
      zdz.classList.add('over');
    }));
    ['dragleave', 'drop'].forEach((ev) => zdz.addEventListener(ev, (e) => {
      e.preventDefault();
      zdz.classList.remove('over');
    }));
    zdz.addEventListener('drop', (e) => {
      const fl = e.dataTransfer && e.dataTransfer.files;
      if (fl && fl.length) zhConvert(fl);
    });
    $('#zh-pick').addEventListener('click', () => $('#zh-file').click());
    $('#zh-file').addEventListener('change', (e) => {
      if (e.target.files.length) zhConvert(e.target.files);
      e.target.value = '';
    });

    // 公版书库
    renderFreeChips();
    $('#free-go').addEventListener('click', () => freeSearch(1));
    $('#free-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') freeSearch(1); });
    $('#free-source').addEventListener('change', () => freeSearch(1));
    $('#free-lang').addEventListener('change', () => freeSearch(1));
    $('#free-cover').addEventListener('change', renderFree);
  }

  async function load(force) {
    try {
      const res = await api('/api/data' + (force ? '?refresh=1' : ''));
      DATA = await res.json();
      renderDevice();
      renderStats();
      renderLibrary();
      renderHighlights();
      renderVocab();
      renderExport();
      if (!$('#epub-routes').children.length) renderEpubRoutes();
      epubLoad();
      calibreLoad(false);
    } catch (e) {
      $('#devtext').textContent = '读取失败：' + e.message;
    }
  }

  bind();
  load(false);
})();
