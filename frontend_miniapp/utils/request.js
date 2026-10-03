const SESSION_KEY = 'duxue_session'
const API_BASE_KEY = 'duxue_api_base_url'
let redirectingToLogin = false

function trimSlash(value) {
  return String(value || '').replace(/\/+$/, '')
}

function getBaseUrl() {
  const saved = wx.getStorageSync(API_BASE_KEY)
  if (saved) return trimSlash(saved)
  try {
    return trimSlash(getApp().globalData.apiBaseUrl)
  } catch (e) {
    return 'http://127.0.0.1:8000/api'
  }
}

function getSession() {
  return wx.getStorageSync(SESSION_KEY) || null
}

function persistSession(session) {
  wx.setStorageSync(SESSION_KEY, session)
  try { getApp().globalData.session = session } catch (e) {}
  return session
}

function saveSession(payload) {
  return persistSession({
    accessToken: payload.access_token,
    userId: payload.user_id,
    loginId: payload.login_id,
    name: payload.name,
    role: payload.role,
    accountStatus: payload.account_status,
    mode: payload.mode,
    mustChangePassword: Boolean(payload.must_change_password),
    canBook: Boolean(payload.can_book),
    canCheckin: Boolean(payload.can_checkin)
  })
}

function updateSessionFromProfile(payload) {
  const current = getSession()
  if (!current || !current.accessToken) return current
  return persistSession({
    ...current,
    userId: payload.user_id,
    loginId: payload.login_id,
    name: payload.name,
    role: payload.role,
    accountStatus: payload.account_status,
    mode: payload.mode,
    mustChangePassword: Boolean(payload.must_change_password),
    canBook: Boolean(payload.can_book),
    canCheckin: Boolean(payload.can_checkin)
  })
}

function clearSession() {
  wx.removeStorageSync(SESSION_KEY)
  try { getApp().globalData.session = null } catch (e) {}
}

function setApiBaseUrl(url) {
  const normalized = trimSlash(url)
  wx.setStorageSync(API_BASE_KEY, normalized)
  return normalized
}

function extractError(res) {
  const data = res && res.data
  if (data && typeof data === 'object' && data.detail) {
    if (Array.isArray(data.detail)) {
      return data.detail.map(item => item.msg || '参数错误').join('；')
    }
    return String(data.detail)
  }
  if (typeof data === 'string' && data) return data
  return `请求失败（HTTP ${res ? res.statusCode : 'unknown'}）`
}

function toQuery(data) {
  if (!data) return ''
  const pairs = Object.keys(data)
    .filter(key => data[key] !== undefined && data[key] !== null && data[key] !== '')
    .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(data[key])}`)
  return pairs.length ? `?${pairs.join('&')}` : ''
}

function redirectLogin() {
  if (redirectingToLogin) return
  redirectingToLogin = true
  clearSession()
  setTimeout(() => {
    wx.reLaunch({
      url: '/pages/login/login',
      complete: () => { redirectingToLogin = false }
    })
  }, 100)
}

function request(options) {
  const {
    url,
    method = 'GET',
    data,
    query,
    auth = true,
    loading = false,
    loadingText = '加载中',
    headers = {}
  } = options

  const session = getSession()
  const header = { 'Content-Type': 'application/json', ...headers }
  if (auth && session && session.accessToken) {
    header.Authorization = `Bearer ${session.accessToken}`
  }

  if (loading) wx.showLoading({ title: loadingText, mask: true })

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getBaseUrl()}${url}${toQuery(query)}`,
      method,
      data,
      header,
      timeout: 20000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
          return
        }
        const error = new Error(extractError(res))
        error.statusCode = res.statusCode
        error.data = res.data
        if (res.statusCode === 401 && auth) redirectLogin()
        reject(error)
      },
      fail(err) {
        const error = new Error(err.errMsg || '网络连接失败')
        error.original = err
        reject(error)
      },
      complete() {
        if (loading) wx.hideLoading()
      }
    })
  })
}

function upload(options) {
  const { url, filePath, name = 'photo', formData = {}, auth = true, loading = true, headers = {} } = options
  const session = getSession()
  const header = { ...headers }
  if (auth && session && session.accessToken) {
    header.Authorization = `Bearer ${session.accessToken}`
  }
  if (loading) wx.showLoading({ title: '正在上传', mask: true })

  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${getBaseUrl()}${url}`,
      filePath,
      name,
      formData,
      header,
      timeout: 30000,
      success(res) {
        let data = res.data
        try { data = JSON.parse(res.data) } catch (e) {}
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(data)
          return
        }
        const fakeRes = { statusCode: res.statusCode, data }
        const error = new Error(extractError(fakeRes))
        error.statusCode = res.statusCode
        error.data = data
        if (res.statusCode === 401 && auth) redirectLogin()
        reject(error)
      },
      fail(err) {
        reject(new Error(err.errMsg || '图片上传失败'))
      },
      complete() {
        if (loading) wx.hideLoading()
      }
    })
  })
}

module.exports = {
  request,
  upload,
  getBaseUrl,
  getSession,
  saveSession,
  updateSessionFromProfile,
  clearSession,
  setApiBaseUrl
}
