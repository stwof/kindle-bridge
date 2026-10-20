const zh = require('../../utils/opencc.js');
const epubUtil = require('../../utils/epub.js');
const file = require('../../utils/file.js');

Page({
  data: {
    input: '',
    output: '',
    busy: false,
    fileName: '',
    fileSize: '',
    stats: ''
  },

  onInput(e) {
    this.setData({ input: e.detail.value });
  },

  // 文本转换
  convertText() {
    const text = this.data.input;
    if (!text.trim()) {
      wx.showToast({ title: '先输入点文字', icon: 'none' });
      return;
    }
    const t = Date.now();
    const out = zh.t2s(text);
    this.setData({
      output: out,
      stats: '转换 ' + text.length + ' 字，耗时 ' + (Date.now() - t) + ' 毫秒'
    });
  },

  clear() {
    this.setData({ input: '', output: '', stats: '' });
  },

  copyOutput() {
    if (!this.data.output) return;
    file.copy(this.data.output).then((ok) => {
      wx.showToast({ title: ok ? '已复制' : '复制失败', icon: 'none' });
    });
  },

  // 文件转换（EPUB / TXT）
  chooseFile() {
    file.chooseFiles(['.epub', '.txt', '.text', '.md'], false)
      .then((files) => {
        if (!files || !files.length) return;
        const f = files[0];
        this.setData({ busy: true, fileName: f.name, fileSize: this._size(f.size) });
        return this._convertFile(f);
      })
      .catch((err) => {
        this.setData({ busy: false });
        wx.showToast({ title: '读取失败', icon: 'none' });
      });
  },

  _size(n) {
    if (!n && n !== 0) return '';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(1) + ' MB';
  },

  _convertFile(f) {
    const ext = file.extname(f.name);
    const t = Date.now();
    if (ext === '.epub') {
      return file.readBuffer(f.path)
        .then((buf) => {
          const r = epubUtil.convertEpub(buf, zh.t2s);
          if (!r.ok) throw new Error(r.error);
          const outName = file.basename(f.name) + '.简体.epub';
          return file.writeFile(outName, r.bytes).then((p) => {
            this.setData({
              busy: false,
              stats: 'EPUB 转换完成：' + r.changed.length + ' 个文件，耗时 ' + (Date.now() - t) + ' 毫秒',
              outPath: p,
              outName: outName
            });
            wx.showToast({ title: '已生成，点下方分享', icon: 'none' });
          });
        })
        .catch((e) => {
          this.setData({ busy: false });
          wx.showToast({ title: (e && e.message) || '转换失败', icon: 'none' });
        });
    }
    // 纯文本
    return file.readText(f.path)
      .then((txt) => {
        const out = zh.t2s(txt);
        const outName = file.basename(f.name) + '.简体.txt';
        return file.writeFile(outName, out).then((p) => {
          this.setData({
            busy: false,
            output: out.length > 2000 ? out.slice(0, 2000) + '\n…（已截断，完整内容在文件里）' : out,
            stats: '文本转换完成：' + txt.length + ' 字，耗时 ' + (Date.now() - t) + ' 毫秒',
            outPath: p,
            outName: outName
          });
          wx.showToast({ title: '已生成，点下方分享', icon: 'none' });
        });
      })
      .catch((e) => {
        this.setData({ busy: false });
        wx.showToast({ title: '转换失败', icon: 'none' });
      });
  },

  shareOut() {
    const p = this.data.outPath;
    if (!p) {
      wx.showToast({ title: '还没有生成文件', icon: 'none' });
      return;
    }
    file.shareFile(p, this.data.outName);
  }
});
