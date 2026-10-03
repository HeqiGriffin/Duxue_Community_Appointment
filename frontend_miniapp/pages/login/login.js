const { request, saveSession, getSession } = require('../../utils/request')
Page({
  data: {
    loginId: '',
    password: '',
    submitting: false,
    changeMode: false,
    oldPassword: '',
    newPassword: '',
    confirmPassword: '',
    displayName: ''
  },
  onLoad() {
    const session = getSession()
    if (session && session.accessToken && !session.mustChangePassword) {
      wx.reLaunch({ url: '/pages/home/home' })
    }
  },
  onLoginIdInput(e) { this.setData({ loginId: e.detail.value.trim() }) },
  onPasswordInput(e) { this.setData({ password: e.detail.value }) },
  onNewPasswordInput(e) { this.setData({ newPassword: e.detail.value }) },
  onConfirmPasswordInput(e) { this.setData({ confirmPassword: e.detail.value }) },
  async submitLogin() {
    const { loginId, password, submitting } = this.data
    if (submitting) return
    if (!loginId || !password) {
      wx.showToast({ title: '请输入学号/工号和密码', icon: 'none' })
      return
    }
    this.setData({ submitting: true })
    try {
      const result = await request({
        url: '/auth/login', method: 'POST', auth: false,
        data: { login_id: loginId, password },
        loading: true, loadingText: '正在登录'
      })
      const session = saveSession(result)
      if (session.mustChangePassword) {
        this.setData({
          changeMode: true,
          oldPassword: password,
          password: '',
          displayName: session.name || session.loginId
        })
        wx.showToast({ title: '首次登录请先修改密码', icon: 'none' })
        return
      }
      wx.reLaunch({ url: '/pages/home/home' })
    } catch (err) {
      wx.showToast({ title: err.message || '登录失败', icon: 'none', duration: 2600 })
    } finally {
      this.setData({ submitting: false })
    }
  },
  async submitPasswordChange() {
    const { oldPassword, newPassword, confirmPassword, submitting } = this.data
    if (submitting) return
    if (newPassword.length < 8) {
      wx.showToast({ title: '新密码至少 8 位', icon: 'none' })
      return
    }
    if (newPassword !== confirmPassword) {
      wx.showToast({ title: '两次输入的新密码不一致', icon: 'none' })
      return
    }
    this.setData({ submitting: true })
    try {
      const result = await request({
        url: '/auth/change-password', method: 'POST',
        data: { old_password: oldPassword, new_password: newPassword },
        loading: true, loadingText: '正在更新'
      })
      saveSession(result)
      wx.showToast({ title: '密码修改成功', icon: 'success' })
      setTimeout(() => wx.reLaunch({ url: '/pages/home/home' }), 500)
    } catch (err) {
      wx.showToast({ title: err.message || '修改失败', icon: 'none', duration: 2600 })
    } finally {
      this.setData({ submitting: false })
    }
  }
})
