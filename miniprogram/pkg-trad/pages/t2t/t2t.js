// 简 -> 繁（台湾正体）
//
// 这一页放在**分包** pkg-trad 里：简->繁 的词组表有 1MB，
// 塞进主包会让小程序首屏变慢，所以等用户真的要点「简转繁」时才下载。
//
// 词组表与转换逻辑来自 opencc-js（OpenCC 的 JavaScript 实现，Apache-2.0）。

const OpenCC = require('../../vendor/cn2t.js');
const tables = require('../../utils/zhtables.js');
const epubUtil = require('../../utils/epub.js');
const file = require('../../utils/file.js');

let _conv = null;

function rawConverter() {
  if (!_conv) {
    // cn -> twp：简体转台湾正体（含词组），输出「裡面 / 網路 / 軟體 / 資訊」
    _conv = OpenCC.Converter({ from: 'cn', to: 'twp' });
  }
  return _conv;
}

Page({
  data: {
    input: '',
    output: '',
    busy: false,
    fileName: '',
    stats: '',
    outPath: '',
    outName: ''
  },

  onInput(e) {
    this.setData({ input: e.detail.value });
  },

  convertText() {
    const text = this.data.input;
    if (!text.trim()) {
      wx.showToast({ title: '先输入点文字', icon: 'none' });
      return;
    }
    const t = Date.now();
    const out = rawConverter()(text);
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

  chooseFile() {
    file.chooseFiles(['.epub', '.txt', '.text', '.md'], false)
      .then((files) => {
        if (!files || !files.length) return;
        const f = files[0];
        this.setData({ busy: true, fileName: f.name });
        return this._convertFile(f);
      })
      .catch(() => {
        this.setData({ busy: false });
      });
  },

  _convertFile(f) {
    const ext = file.extname(f.name);
    const t = Date.now();
    const conv = rawConverter();
    if (ext === '.epub') {
      return file.readBuffer(f.path)
        .then((buf) => {
          const r = epubUtil.convertEpub(buf, conv);
          if (!r.ok) throw new Error(r.error);
          const outName = file.basename(f.name) + '.繁體.epub';
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
    return file.readText(f.path)
      .then((txt) => {
        const out = conv(txt);
        const outName = file.basename(f.name) + '.繁體.txt';
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
      .catch(() => {
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
