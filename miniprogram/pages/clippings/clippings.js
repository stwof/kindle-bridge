const cl = require('../../utils/clippings.js');
const file = require('../../utils/file.js');

Page({
  data: {
    fileName: '',
    busy: false,
    total: 0,
    books: [],
    preview: [],
    stats: ''
  },

  chooseFile() {
    file.chooseFiles(['.txt'], false)
      .then((files) => {
        if (!files || !files.length) return;
        const f = files[0];
        this.setData({ busy: true, fileName: f.name });
        return file.readText(f.path)
          .then((raw) => {
            const clips = cl.parseClippings(raw, true);
            const groups = cl.groupByBook(clips);
            const preview = [];
            for (let i = 0; i < groups.length && preview.length < 30; i++) {
              const g = groups[i];
              for (let j = 0; j < g.items.length && preview.length < 30; j++) {
                const it = g.items[j];
                preview.push({
                  key: g.title + '#' + j,
                  title: g.title,
                  author: g.author,
                  type: cl.TYPE_LABEL[it.type] || it.type,
                  page: it.page,
                  location: it.location,
                  added_at: it.added_at,
                  text: it.text.length > 220 ? it.text.slice(0, 220) + '…' : it.text
                });
              }
            }
            this.setData({
              busy: false,
              total: clips.length,
              books: groups.map((g) => ({ title: g.title, author: g.author, n: g.items.length })),
              preview: preview,
              stats: '共解析出 ' + clips.length + ' 条，覆盖 ' + groups.length + ' 本书'
            });
            this._groups = groups;
          })
          .catch(() => {
            this.setData({ busy: false });
            wx.showToast({ title: '解析失败', icon: 'none' });
          });
      })
      .catch(() => {
        this.setData({ busy: false });
      });
  },

  // ---- 导出 ----

  doExport(e) {
    const kind = e.currentTarget.dataset.kind;
    const groups = this._groups;
    if (!groups || !groups.length) {
      wx.showToast({ title: '先选一个标注文件', icon: 'none' });
      return;
    }
    let body = '';
    let name = '';
    if (kind === 'md') {
      body = this._markdown(groups);
      name = 'Kindle标注_Markdown.txt';
    } else if (kind === 'csv') {
      body = this._csv(groups);
      name = 'Kindle标注.csv';
    } else if (kind === 'weread') {
      body = this._weread(groups);
      name = '微信读书笔记.txt';
    } else {
      body = JSON.stringify({
        generator: 'Kindle 桥 · 微信小程序',
        books: groups
      }, null, 2);
      name = 'Kindle标注.json';
    }
    file.writeFile(name, body)
      .then((p) => file.shareFile(p, name))
      .then(() => wx.showToast({ title: '已生成', icon: 'none' }))
      .catch(() => wx.showToast({ title: '导出失败', icon: 'none' }));
  },

  _markdown(groups) {
    let out = '# Kindle 标注\n\n';
    for (const g of groups) {
      out += '## ' + g.title + (g.author ? ' —— ' + g.author : '') + '\n\n';
      for (const it of g.items) {
        const meta = [cl.TYPE_LABEL[it.type] || it.type];
        if (it.page) meta.push('第 ' + it.page + ' 页');
        if (it.location) meta.push('位置 ' + it.location);
        if (it.added_at) meta.push(it.added_at);
        out += '> ' + it.text.replace(/\n/g, '\n> ') + '\n>\n> — ' + meta.join(' · ') + '\n\n';
      }
    }
    return out;
  },

  _csv(groups) {
    const esc = (s) => {
      const v = String(s == null ? '' : s);
      return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
    };
    const rows = [['书名', '作者', '类型', '页码', '位置', '时间', '内容']];
    for (const g of groups) {
      for (const it of g.items) {
        rows.push([g.title, g.author || '', cl.TYPE_LABEL[it.type] || '',
          it.page || '', it.location || '', it.added_at || '', it.text]);
      }
    }
    return rows.map((r) => r.map(esc).join(',')).join('\n');
  },

  _weread(groups) {
    let out = '';
    for (const g of groups) {
      out += '《' + g.title + '》' + (g.author ? ' ' + g.author : '') + '\n\n';
      for (const it of g.items) {
        out += it.text + '\n\n';
      }
      out += '\n';
    }
    return out;
  },

  copyPreview() {
    const groups = this._groups;
    if (!groups || !groups.length) return;
    file.copy(this._weread(groups)).then((ok) => {
      wx.showToast({ title: ok ? '已复制' : '复制失败', icon: 'none' });
    });
  }
});
