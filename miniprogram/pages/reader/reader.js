// 小程序原生 EPUB 阅读器页面
// 完全离线：从微信会话里选一个 .epub，本地解析、本地读，不联网、不上传。

const reader = require('../../utils/reader.js');

// 不用 wx.arrayBufferToBase64（部分基础库已废弃），自己实现一个，Node 里也能跑
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
function bytesToBase64(bytes) {
  let s = '';
  const len = bytes.length;
  for (let i = 0; i < len; i += 3) {
    const b0 = bytes[i];
    const b1 = bytes[i + 1];
    const b2 = bytes[i + 2];
    s += B64[b0 >> 2];
    s += B64[((b0 & 3) << 4) | (b1 !== undefined ? b1 >> 4 : 0)];
    s += b1 !== undefined ? B64[((b1 & 15) << 2) | (b2 !== undefined ? b2 >> 6 : 0)] : '=';
    s += b2 !== undefined ? B64[b2 & 63] : '=';
  }
  return s;
}

Page({
  data: {
    state: 'idle',            // idle | loading | reading | error
    errorMsg: '',
    title: '', author: '',
    chapterTitle: '',
    blocks: [],              // 当前章渲染块：{type:'p',text} 或 {type:'img',src}
    toc: [],
    tocOpen: false,
    panelOpen: false,
    theme: 'light',
    fontSize: 34,            // rpx
    chapterIndex: 0,
    totalChapters: 0,
    hasPrev: false, hasNext: false,
    progressText: '',
  },
  book: null,
  fileKey: '',

  onLoad() {
    const p = wx.getStorageSync('reader_prefs') || {};
    this.setData({ theme: p.theme || 'light', fontSize: p.fontSize || 34 });
  },

  chooseFile() {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['epub'],
      success: (res) => {
        const f = res.tempFiles && res.tempFiles[0];
        if (!f) return;
        this.loadFile(f.path, f.name || 'book.epub', f.size || 0);
      },
      fail: (e) => {
        if (e && e.errMsg && !/cancel|fail cancel/.test(e.errMsg)) {
          wx.showToast({ title: '选择失败', icon: 'none' });
        }
      },
    });
  },

  loadFile(path, name, size) {
    this.setData({ state: 'loading', errorMsg: '' });
    const fs = wx.getFileSystemManager();
    fs.readFile({
      filePath: path,
      success: (r) => {
        const bytes = new Uint8Array(r.data);
        const book = reader.parseEpub(bytes);
        if (book.error) {
          this.setData({ state: 'error', errorMsg: book.error });
          return;
        }
        this.book = book;
        this.fileKey = name + ':' + size;
        let idx = 0;
        const saved = wx.getStorageSync('reader_progress:' + this.fileKey);
        if (typeof saved === 'number' && saved >= 0 && saved < book.chapters.length) idx = saved;
        this.setData({
          title: book.title,
          author: book.author,
          toc: book.toc,
          totalChapters: book.chapters.length,
          state: 'reading',
        });
        this.showChapter(idx);
      },
      fail: () => this.setData({ state: 'error', errorMsg: '读取文件失败（可能太大或不是 EPUB）' }),
    });
  },

  showChapter(idx) {
    const book = this.book;
    if (!book) return;
    const ch = book.chapters[idx];
    if (!ch) return;
    const blocks = ch.blocks.map((b) => {
      if (b.type === 'img') {
        const uri = 'data:image/' + (b.ext || 'png') + ';base64,' + bytesToBase64(b.bytes);
        return { type: 'img', src: uri };
      }
      return { type: 'p', text: b.text };
    });
    this.setData({
      chapterIndex: idx,
      chapterTitle: ch.title,
      blocks,
      hasPrev: idx > 0,
      hasNext: idx < book.chapters.length - 1,
      progressText: (idx + 1) + ' / ' + book.chapters.length,
    });
    wx.setStorageSync('reader_progress:' + this.fileKey, idx);
    // 每次换章滚回顶部
    wx.createSelectorQuery().select('#rscroll').scrollTo({ top: 0, duration: 0 }).exec();
  },

  prevChapter() {
    if (this.data.chapterIndex > 0) this.showChapter(this.data.chapterIndex - 1);
  },
  nextChapter() {
    if (this.data.chapterIndex < this.data.totalChapters - 1) this.showChapter(this.data.chapterIndex + 1);
  },

  // 横向滑动翻章（竖向滑动留给正常阅读滚动）
  onTouchStart(e) {
    const t = e.touches[0];
    this._sx = t.clientX; this._sy = t.clientY;
  },
  onTouchEnd(e) {
    if (this._sx == null) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - this._sx;
    const dy = t.clientY - this._sy;
    this._sx = null;
    if (Math.abs(dy) > 120) return;       // 竖向滑动，不当成翻页
    if (dx < -55) this.nextChapter();
    else if (dx > 55) this.prevChapter();
  },

  openToc() { this.setData({ tocOpen: true, panelOpen: false }); },
  closeToc() { this.setData({ tocOpen: false }); },
  jumpToc(e) {
    const i = +e.currentTarget.dataset.i;
    if (i >= 0) this.showChapter(i);
    this.setData({ tocOpen: false });
  },

  togglePanel() { this.setData({ panelOpen: !this.data.panelOpen, tocOpen: false }); },
  pickTheme(e) {
    const theme = e.currentTarget.dataset.theme;
    this.setData({ theme });
    this._savePrefs();
  },
  fontDelta(e) {
    const d = +e.currentTarget.dataset.d;
    const f = Math.max(26, Math.min(52, this.data.fontSize + d));
    this.setData({ fontSize: f });
    this._savePrefs();
  },
  _savePrefs() {
    wx.setStorageSync('reader_prefs', { theme: this.data.theme, fontSize: this.data.fontSize });
  },

  goBack() {
    wx.navigateBack({ delta: 1, fail: () => this.setData({ state: 'idle' }) });
  },
  noop() {},
});
