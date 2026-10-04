wx.cloud.init({
  env: 'love-my-duxue-d7gve6bvl44cda5f7',
  traceUser: true,
})

App({
  globalData: {
    // 微信开发者工具使用本地联调地址；真机请求由 utils/request.js 通过 CloudBase AnyService 转发。
    apiBaseUrl: 'http://127.0.0.1:8000/api',
    campusTimezone: '+08:00',
    session: null,
    cloudEnvId: "love-my-duxue-d7gve6bvl44cda5f7",  // 替换为你的云开发环境ID
    anyServiceName: "duxue"     // 替换AnyService服务标识
  },
  onLaunch() {
    this.globalData.session = wx.getStorageSync('duxue_session') || null
    // 初始化云开发
    wx.cloud.init({
      env: this.globalData.cloudEnvId,
      traceUser: true
    })
  },
  setSession(session) {
    this.globalData.session = session
    wx.setStorageSync('duxue_session', session)
  },
  clearSession() {
    this.globalData.session = null
    wx.removeStorageSync('duxue_session')
  }
})
