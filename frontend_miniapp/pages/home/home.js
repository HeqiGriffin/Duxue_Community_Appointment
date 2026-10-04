const { request, getSession, updateSessionFromProfile, clearSession } = require('../../utils/request')

const STATUS_META = {
  pending_ai: ['AI 审核中', 'pending'],
  pending_manual: ['待人工审核', 'pending'],
  approved: ['待签到', 'success'],
  rejected: ['已驳回', 'danger'],
  invalidated: ['场地冲突失效', 'danger'],
  active: ['已签到', 'active'],
  awaiting_cleanup: ['待离场实拍', 'warning'],
  completed: ['已完成', 'done'],
  expired: ['未签到已过期', 'muted'],
  cancelled: ['已取消', 'muted']
}

function campusTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  const c = new Date(d.getTime() + 8 * 60 * 60 * 1000)
  const pad = n => String(n).padStart(2, '0')
  return `${c.getUTCMonth() + 1}月${c.getUTCDate()}日 ${pad(c.getUTCHours())}:${pad(c.getUTCMinutes())}`
}

function toCampusMs(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 0 : d.getTime()
}

Page({
  data: {
    session: null,
    bookings: [],
    loading: false,
    frozen: false,
    greeting: '你好',
    stats: { pending: 0, upcoming: 0, cleanup: 0 }
  },

  onShow() { this.refreshAll() },
  onPullDownRefresh() { this.refreshAll(true) },

  async refreshAll(fromPull = false) {
    const session = getSession()
    if (!session || !session.accessToken) {
      wx.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.setData({ loading: true, session })
    try {
      const [profile, bookingResult] = await Promise.all([
        request({ url: '/auth/me' }),
        request({ url: '/bookings/me', query: { limit: 50, offset: 0 } })
      ])
      const nextSession = updateSessionFromProfile(profile)
      const bookings = (bookingResult.items || []).map(item => this.decorateBooking(item))
      const stats = {
        pending: bookings.filter(x => ['pending_ai', 'pending_manual'].includes(x.status)).length,
        upcoming: bookings.filter(x => x.status === 'approved').length,
        cleanup: bookings.filter(x => x.status === 'awaiting_cleanup' || x.canUploadCleanup).length
      }
      this.setData({
        session: nextSession,
        frozen: nextSession.accountStatus === 'frozen',
        bookings,
        stats,
        greeting: this.getGreeting()
      })
    } catch (err) {
      if (err.statusCode !== 401) wx.showToast({ title: err.message || '刷新失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
      if (fromPull) wx.stopPullDownRefresh()
    }
  },

  getGreeting() {
    const hour = new Date(Date.now() + 8 * 3600000).getUTCHours()
    if (hour < 6) return '夜深了'
    if (hour < 12) return '早上好'
    if (hour < 18) return '下午好'
    return '晚上好'
  },

  decorateBooking(item) {
    const meta = STATUS_META[item.status] || [item.status, 'muted']
    const now = Date.now()
    const startMs = toCampusMs(item.start_time)
    const endMs = toCampusMs(item.end_time)
    const canCheckin = item.status === 'approved' && now >= startMs - 60 * 60 * 1000 && now <= startMs + 60 * 60 * 1000
    const canUploadCleanup = ['active', 'awaiting_cleanup'].includes(item.status) && now >= endMs - 30 * 60 * 1000 && now <= endMs + 30 * 60 * 1000
    return {
      ...item,
      statusText: meta[0],
      statusClass: meta[1],
      timeText: `${campusTime(item.start_time)} - ${campusTime(item.end_time).split(' ').pop()}`,
      roomText: item.room_code || item.requested_room_code || '待分配',
      usageModeText: item.usage_mode === 'study' ? '自习共享' : '非自习独占',
      canCheckin,
      canUploadCleanup,
      canAppeal: item.status === 'rejected',
      showAction: canCheckin || canUploadCleanup || item.status === 'rejected'
    }
  },

  goAppointment() {
    if (this.data.frozen || !this.data.session.canBook) {
      wx.showToast({ title: '当前账号不可发起预约', icon: 'none' })
      return
    }
    wx.navigateTo({ url: '/pages/appointment/appointment' })
  },

  goCheckinList() {
    const candidate = this.data.bookings.find(x => x.canCheckin || x.canUploadCleanup || ['approved', 'active', 'awaiting_cleanup'].includes(x.status))
    if (!candidate) {
      wx.showToast({ title: '暂无可签到或待离场的预约', icon: 'none' })
      return
    }
    wx.navigateTo({ url: `/pages/checkin/checkin?bookingId=${candidate.id}` })
  },

  openBooking(e) {
    const id = Number(e.currentTarget.dataset.id)
    wx.navigateTo({ url: `/pages/checkin/checkin?bookingId=${id}` })
  },

  goAppeal() { wx.navigateTo({ url: '/pages/online_appeal/online_appeal' }) },

  goBookingAppeal(e) {
    const id = Number(e.currentTarget.dataset.id)
    if (!id) return
    wx.navigateTo({ url: `/pages/online_appeal/online_appeal?bookingId=${id}` })
  },

  showSystemNotice() {
    wx.showModal({
      title: '系统通知',
      content: '预约审核、待使用与待离场状态会在首页实时更新。微信服务通知需要在正式小程序后台配置消息模板后接入，目前不伪造未配置的推送能力。',
      showCancel: false
    })
  },

  logout() {
    wx.showModal({
      title: '退出登录', content: '确定退出当前账号吗？',
      success: res => {
        if (!res.confirm) return
        clearSession()
        wx.reLaunch({ url: '/pages/login/login' })
      }
    })
  }
})
