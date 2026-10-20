const vc = require('../../utils/vocab.js');
const file = require('../../utils/file.js');

Page({
  data: {
    fileName: '',
    busy: false,
    total: 0,
    zh: 0,
    en: 0,
    preview: [],
    stats: ''
  },

  chooseFile() {
    file.chooseFiles(['.csv'], false)
      .then((files) => {
        if (!files || !files.length) return;
        const f = files[0];
        this.setData({ busy: true, fileName: f.name });
        return file.readText(f.path)
          .then((text) => {
            const r = vc.parseVocabCsv(text);
            const words = r.words;
            let zh = 0;
            let en = 0;
            for (const w of words) {
              if (w.lang === 'zh') zh++; else en++;
            }
            this.setData({
              busy: false,
              total: words.length,
              zh: zh,
              en: en,
              preview: words.slice(0, 40),
              stats: words.length
                ? ('共 ' + words.length + ' 个词（中文 ' + zh + '，英文 ' + en + '）')
                : '没解析出词条 —— 确认选的是桌面端「生词」页导出的《Kindle生词本.csv》'
            });
            this._words = words;
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

  doExport(e) {
    const kind = e.currentTarget.dataset.kind;
    const words = this._words;
    if (!words || !words.length) {
      wx.showToast({ title: '先选一个生词 CSV', icon: 'none' });
      return;
    }
    let body = '';
    let name = '';
    if (kind === 'anki') {
      body = vc.toAnki(words);
      name = 'Kindle生词_Anki.txt';
    } else if (kind === 'md') {
      body = vc.toMarkdown(words);
      name = 'Kindle生词本.md';
    } else {
      body = vc.toJson(words);
      name = 'Kindle生词本.json';
    }
    file.writeFile(name, body)
      .then((p) => file.shareFile(p, name))
      .then(() => wx.showToast({ title: '已生成', icon: 'none' }))
      .catch(() => wx.showToast({ title: '导出失败', icon: 'none' }));
  }
});
