const { request, upload } = require('../../utils/request')
const { takePhoto } = require('../../utils/camera')

const HOUR_MS = 60 * 60 * 1000

function campusTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  const c = new Date(d.getTime() + 8 * 3600000)
  const pad = n => String(n).padStart(2, '0')
  return `${c.getUTCFullYear()}-${pad(c.getUTCMonth()+1)}-${pad(c.getUTCDate())} ${pad(c.getUTCHours())}:${pad(c.getUTCMinutes())}`
}

function statusText(status) {
  return ({ pending_ai:'AI 审核中', pending_manual:'待人工审核', approved:'待签到', rejected:'已驳回', invalidated:'场地冲突失效', active:'已签到', awaiting_cleanup:'待离场实拍', completed:'已完成', expired:'未签到已过期', cancelled:'已取消' })[status] || status
}

Page({
  data: {
    bookingId: null,
    booking: null,
    statusText: '',
    timeText: '',
    loading: true,
    checkingIn: false,
    uploading: false,
    canCheckin: false,
    canCleanup: false,
    checkinHint: '',
    checkedInText: '',
    cleanupResult: null
  },

  onLoad(options) {
    const bookingId = Number(options.bookingId)
    if (!bookingId) {
      wx.showModal({ title: '缺少预约', content: '请从首页选择一条预约记录进入。', showCancel: false, success: () => wx.navigateBack() })
      return
    }
    this.setData({ bookingId })
    this.loadBooking()
  },

  onShow() {
    if (this.data.bookingId) this.loadBooking(false)
  },

  async loadBooking(showError = true) {
    try {
      const booking = await request({ url: `/bookings/${this.data.bookingId}` })
      const now = Date.now()
      const start = new Date(booking.start_time).getTime()
      const end = new Date(booking.end_time).getTime()
      const windowStart = start - HOUR_MS
      const windowEnd = start + HOUR_MS
      const alreadyCheckedIn = Boolean(booking.checked_in_at) || booking.status === 'active' || booking.status === 'awaiting_cleanup' || booking.status === 'completed'
      const canCheckin = booking.status === 'approved' && now >= windowStart && now <= windowEnd
      const canCleanup = ['active', 'awaiting_cleanup'].includes(booking.status) && now >= end

      let checkinHint = ''
      if (alreadyCheckedIn) {
        checkinHint = '本次预约已完成签到'
      } else if (booking.status !== 'approved') {
        checkinHint = booking.status === 'expired' ? '本次预约因未在规定时间内签到而过期' : '当前预约状态不可签到'
      } else if (now < windowStart) {
        checkinHint = `签到将在 ${campusTime(new Date(windowStart).toISOString())} 开放`
      } else if (now > windowEnd) {
        checkinHint = '签到时间已结束'
      } else {
        checkinHint = '当前可以签到'
      }

      this.setData({
        booking,
        statusText: statusText(booking.status),
        timeText: `${campusTime(booking.start_time)} 至 ${campusTime(booking.end_time)}`,
        canCheckin,
        canCleanup,
        checkinHint,
        checkedInText: booking.checked_in_at ? campusTime(booking.checked_in_at) : '',
        loading: false
      })
    } catch (err) {
      this.setData({ loading: false })
      if (showError) wx.showToast({ title: err.message || '读取预约失败', icon: 'none' })
    }
  },

  async doCheckin() {
    if (this.data.checkingIn) return
    this.setData({ checkingIn: true })
    try {
      await request({
        url: `/checkin/${this.data.bookingId}`,
        method: 'POST',
        loading: true,
        loadingText: '正在签到'
      })
      wx.showToast({ title: '签到成功', icon: 'success' })
      await this.loadBooking(false)
    } catch (err) {
      wx.showToast({ title: err.message || '签到失败', icon: 'none', duration: 3000 })
    } finally {
      this.setData({ checkingIn: false })
    }
  },

  async takeAndUpload() {
    if (this.data.uploading) return
    this.setData({ uploading: true })
    try {
      const photo = await takePhoto()
      const result = await upload({
        url: `/cleanup/${this.data.bookingId}`,
        filePath: photo.path,
        name: 'photo',
        formData: { camera_source: 'camera' }
      })
      this.setData({ cleanupResult: result, canCleanup: false })
      const text = result.review_status === 'auto_pass' ? '照片已提交并自动核验通过' : '照片已提交，等待人工核验'
      wx.showModal({ title: '离场提交成功', content: text, showCancel: false })
      await this.loadBooking(false)
    } catch (err) {
      if (err.message !== '已取消拍照') wx.showToast({ title: err.message || '提交失败', icon: 'none', duration: 3000 })
    } finally {
      this.setData({ uploading: false })
    }
  }
})
