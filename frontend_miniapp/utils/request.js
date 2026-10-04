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

// 判断是否真机环境，走AnyService网关，增加打印日志
function isUseCloudContainer() {
  const sysInfo = wx.getSystemInfoSync()
  console.log("platform = ", sysInfo.platform)
  const flag = sysInfo.platform !== 'devtools'
  console.log("是否走AnyService：", flag)
  return flag
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
    // ========== 真机：AnyService callContainer 分支 ==========
    if(isUseCloudContainer()){
      const app = getApp()
      const fullPath = '/api' + url + toQuery(query)
      console.log("====AnyService请求信息====")
      console.log("envId:",app.globalData.cloudEnvId)
      console.log("serviceName:",app.globalData.anyServiceName)
      console.log("path:",fullPath)

      const callPromise = wx.cloud.callContainer({
        path: fullPath,
        header: {
          "X-WX-SERVICE": "tcbanyservice",
          "X-AnyService-Name": app.globalData.anyServiceName,
          ...header
        },
        method,
        data,
        timeout:20000
      })
      // 20s超时兜底
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(()=>{
          reject(new Error("请求超时，请检查网络或服务配置"))
        }, 20000)
      })

      Promise.race([callPromise, timeoutPromise])
      .then(res=>{
        console.log("callContainer成功返回：",res)
        const fakeRes = {
          statusCode: res.statusCode || 200,
          data: res.data
        }
        if (fakeRes.statusCode >= 200 && fakeRes.statusCode < 300) {
          resolve(fakeRes.data)
          return
        }
        const error = new Error(extractError(fakeRes))
        error.statusCode = fakeRes.statusCode
        error.data = fakeRes.data
        if (fakeRes.statusCode === 401 && auth) redirectLogin()
        reject(error)
      })
      .catch(err=>{
        console.error("callContainer捕获异常：",err)
        const error = new Error(err.errMsg || err.message || '网络连接失败')
        error.original = err
        reject(error)
      })
      .finally(()=>{
        if (loading) wx.hideLoading()
      })
      return
    }

    // ========== 模拟器：保留原来wx.request 本地调试分支 ==========
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

// upload函数：仅模拟器本地可用，真机上传暂不支持
function upload(options) {
  const {
    url,
    filePath,
    name = 'photo',
    formData = {},
    auth = true,
    loading = true,
    headers = {}
  } = options

  const session = getSession()

  if (loading) {
    wx.showLoading({
      title: '正在上传',
      mask: true
    })
  }

  // ===== 真机：CloudBase 临时存储 + AnyService =====
  if (isUseCloudContainer()) {
    let cloudFileId = ''

    const randomPart = Math.random()
      .toString(36)
      .slice(2, 10)

    const cloudPath =
      `duxue-temp/cleanup/${Date.now()}_${randomPart}.jpg`

    return wx.cloud.uploadFile({
      cloudPath,
      filePath
    })
      .then(uploadRes => {
        cloudFileId = uploadRes.fileID

        if (!cloudFileId) {
          throw new Error('云存储未返回文件 ID')
        }

        return wx.cloud.getTempFileURL({
          fileList: [cloudFileId]
        })
      })
      .then(urlRes => {
        const item =
          urlRes.fileList &&
          urlRes.fileList[0]

        if (
          !item ||
          item.status !== 0 ||
          !item.tempFileURL
        ) {
          throw new Error(
            (item && item.errMsg) ||
            '无法获取照片临时地址'
          )
        }

        // 继续使用已经打通的 AnyService JSON 通道。
        return request({
          url: `${url}/cloud`,
          method: 'POST',
          data: {
            temp_url: item.tempFileURL,
            camera_source:
              formData.camera_source || 'camera'
          },
          auth,
          loading: false,
          headers
        })
      })
      .finally(() => {
        // FastAPI 已保存正式副本，因此 CloudBase 这里只作为中转。
        if (cloudFileId) {
          wx.cloud.deleteFile({
            fileList: [cloudFileId]
          }).catch(err => {
            console.warn(
              '临时云文件删除失败：',
              err
            )
          })
        }

        if (loading) {
          wx.hideLoading()
        }
      })
  }

  // ===== 微信开发者工具：原来的本地 multipart 调试 =====
  const header = { ...headers }

  if (
    auth &&
    session &&
    session.accessToken
  ) {
    header.Authorization =
      `Bearer ${session.accessToken}`
  }

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

        try {
          data = JSON.parse(res.data)
        } catch (e) {}

        if (
          res.statusCode >= 200 &&
          res.statusCode < 300
        ) {
          resolve(data)
          return
        }

        const fakeRes = {
          statusCode: res.statusCode,
          data
        }

        const error =
          new Error(extractError(fakeRes))

        error.statusCode =
          res.statusCode

        error.data = data

        if (
          res.statusCode === 401 &&
          auth
        ) {
          redirectLogin()
        }

        reject(error)
      },

      fail(err) {
        reject(
          new Error(
            err.errMsg ||
            '图片上传失败'
          )
        )
      },

      complete() {
        if (loading) {
          wx.hideLoading()
        }
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
