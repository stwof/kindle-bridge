// Kindle 桥 · 微信小程序
// 全部功能在手机本地完成，不上传任何数据，也不需要服务器。
App({
  globalData: {
    version: '1.0.0',
    // 桌面端项目地址：填上就能从手机跳到电脑上的 Kindle 桥网页版
    bridgeUrl: ''
  },
  onLaunch() {
    const info = wx.getAccountInfoSync ? wx.getAccountInfoSync() : null;
    if (info && info.miniProgram && info.miniProgram.version) {
      this.globalData.version = info.miniProgram.version;
    }
  }
});
