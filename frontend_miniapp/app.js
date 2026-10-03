App({
  globalData: {
    // 微信开发者工具本地联调默认地址；真机/生产必须改为已备案 HTTPS 业务域名。
    apiBaseUrl: 'http://127.0.0.1:8000/api',
    campusTimezone: '+08:00',
    session: null
  },

  onLaunch() {
    this.globalData.session = wx.getStorageSync('duxue_session') || null
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
