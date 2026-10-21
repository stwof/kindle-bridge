const app = getApp();

Page({
  data: {
    version: '',
    features: [
      {
        key: 'convert',
        icon: '⇄',
        title: '繁 → 简 转换',
        desc: '文本或 EPUB/TXT，一键转简体。字典来自 OpenCC，完全离线。',
        page: '/pages/convert/convert'
      },
      {
        key: 't2t',
        icon: '⇄',
        title: '简 → 繁 转换',
        desc: '转成台湾正体（裡面 / 網路 / 軟體）。词组表较大，按需加载。',
        page: '/pkg-trad/pages/t2t/t2t'
      },
      {
        key: 'clippings',
        icon: '✎',
        title: '标注解析',
        desc: '解析 My Clippings.txt，导出 Markdown / CSV / 微信读书笔记。',
        page: '/pages/clippings/clippings'
      },
      {
        key: 'vocab',
        icon: '词',
        title: '生词本',
        desc: '把桌面端导出的生词 CSV 转成 Anki 词库。',
        page: '/pages/vocab/vocab'
      },
      {
        key: 'reader',
        icon: '📖',
        title: '读 EPUB',
        desc: '离线阅读器：从微信选一个 .epub，横向滑动翻章，支持目录与主题。',
        page: '/pages/reader/reader'
      }
    ]
  },
  onLoad() {
    this.setData({ version: (app && app.globalData && app.globalData.version) || '1.0.0' });
  },
  go(e) {
    const url = e.currentTarget.dataset.url;
    if (!url) return;
    wx.navigateTo({ url: url });
  }
});
