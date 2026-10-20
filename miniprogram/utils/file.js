// 文件选择 / 读取 / 保存 / 分享 —— 小程序侧的通用文件操作。
// 全部走用户自己的微信文件系统，不经过任何服务器。

const fs = wx.getFileSystemManager();

/**
 * 从微信聊天记录里选文件（Kindle 桥桌面端导出的 CSV、TXT、EPUB 都能选）。
 * @param {string[]} ext  允许的扩展名，如 ['.epub', '.txt']
 */
function chooseFiles(ext, multiple) {
  return new Promise((resolve, reject) => {
    wx.chooseMessageFile({
      count: multiple === false ? 1 : 20,
      type: 'file',
      extension: (ext || []).map((e) => e.replace(/^\./, '')),
      success: (res) => resolve(res.tempFiles || []),
      fail: (err) => {
        if (err && /cancel/i.test(err.errMsg || '')) resolve([]);
        else reject(err);
      }
    });
  });
}

/** 读文件为 ArrayBuffer */
function readBuffer(filePath) {
  return new Promise((resolve, reject) => {
    fs.readFile({
      filePath: filePath,
      success: (res) => resolve(res.data),
      fail: reject
    });
  });
}

/** 读文件为文本（自动去掉 UTF-8 BOM） */
function readText(filePath) {
  return new Promise((resolve, reject) => {
    fs.readFile({
      filePath: filePath,
      encoding: 'utf8',
      success: (res) => {
        let t = res.data || '';
        if (t.charCodeAt(0) === 0xfeff) t = t.slice(1);
        resolve(t);
      },
      fail: reject
    });
  });
}

/** 写到小程序自己的目录，返回新文件路径 */
function writeFile(name, data) {
  const p = wx.env.USER_DATA_PATH + '/' + name;
  return new Promise((resolve, reject) => {
    fs.writeFile({
      filePath: p,
      data: data,
      success: () => resolve(p),
      fail: reject
    });
  });
}

/** 把文件分享到微信聊天 */
function shareFile(filePath, filename) {
  return new Promise((resolve) => {
    wx.shareFileMessage({
      filePath: filePath,
      filename: filename || '',
      success: () => resolve(true),
      fail: (err) => {
        if (err && /cancel/i.test(err.errMsg || '')) resolve(false);
        else {
          wx.showToast({ title: '分享失败', icon: 'none' });
          resolve(false);
        }
      }
    });
  });
}

/** 复制到剪贴板 */
function copy(text) {
  return new Promise((resolve) => {
    wx.setClipboardData({
      data: text,
      success: () => resolve(true),
      fail: () => resolve(false)
    });
  });
}

/** 生成带时间戳的文件名，避免同名覆盖 */
function stamp() {
  const d = new Date();
  const p = (n) => (n < 10 ? '0' + n : '' + n);
  return '' + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) +
    '-' + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
}

/** 文件名去扩展名 */
function basename(name) {
  const i = name.lastIndexOf('.');
  return i > 0 ? name.slice(0, i) : name;
}

/** 扩展名（小写，含点） */
function extname(name) {
  const i = name.lastIndexOf('.');
  return i > 0 ? name.slice(i).toLowerCase() : '';
}

module.exports = { chooseFiles, readBuffer, readText, writeFile, shareFile, copy, stamp, basename, extname };
