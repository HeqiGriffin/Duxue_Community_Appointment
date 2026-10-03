wx.cloud.init({
  env: 'love-my-duxue-d7gve6bvl44cda5f7',
  traceUser: true,
})

App({
  globalData: {
    // 微信开发者工具本地联调默认地址；真机/生产必须改为已备案 HTTPS 业务域名。
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
