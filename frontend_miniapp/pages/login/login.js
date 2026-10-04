const { request, saveSession, getSession } = require('../../utils/request')

function validPassword(value) {
  return /[A-Za-z]/.test(value) && /\d/.test(value)
}

Page({
  data: {
    loginId: '',
    password: '',
    submitting: false,
    changeMode: false,
    oldPassword: '',
    newPassword: '',
    confirmPassword: '',
    displayName: '',
    errorMessage: ''
  },
  onLoad() {
    const session = getSession()
    if (session && session.accessToken && !session.mustChangePassword) {
      wx.reLaunch({ url: '/pages/home/home' })
    }
  },
  onLoginIdInput(e) { this.setData({ loginId: e.detail.value.trim(), errorMessage: '' }) },
  onPasswordInput(e) { this.setData({ password: e.detail.value, errorMessage: '' }) },
  onNewPasswordInput(e) { this.setData({ newPassword: e.detail.value, errorMessage: '' }) },
  onConfirmPasswordInput(e) { this.setData({ confirmPassword: e.detail.value, errorMessage: '' }) },
  async submitLogin() {
    const { loginId, password, submitting } = this.data
    if (submitting) return
    if (!loginId || !password) {
      this.setData({ errorMessage: '请输入学号/工号和密码' })
      return
    }
    this.setData({ submitting: true, errorMessage: '' })
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
          displayName: session.name || session.loginId,
          errorMessage: ''
        })
        wx.showToast({ title: '首次登录请先修改密码', icon: 'none' })
        return
      }
      wx.reLaunch({ url: '/pages/home/home' })
    } catch (err) {
      const message = err.message || '登录失败'
      this.setData({ errorMessage: message })
    } finally {
      this.setData({ submitting: false })
    }
  },
  async submitPasswordChange() {
    const { oldPassword, newPassword, confirmPassword, submitting } = this.data
    if (submitting) return
    if (!validPassword(newPassword)) {
      this.setData({ errorMessage: '新密码必须同时包含字母和数字，其他字符可自由使用' })
      return
    }
    if (newPassword !== confirmPassword) {
      this.setData({ errorMessage: '两次输入的新密码不一致' })
      return
    }
    this.setData({ submitting: true, errorMessage: '' })
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
      this.setData({ errorMessage: err.message || '修改失败' })
    } finally {
      this.setData({ submitting: false })
    }
  }
})
