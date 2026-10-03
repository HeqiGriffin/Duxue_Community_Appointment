const { request, upload } = require('../../utils/request')
const { takePhoto } = require('../../utils/camera')

function campusTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  const c = new Date(d.getTime() + 8 * 3600000)
  const pad = n => String(n).padStart(2, '0')
  return `${c.getUTCFullYear()}-${pad(c.getUTCMonth()+1)}-${pad(c.getUTCDate())} ${pad(c.getUTCHours())}:${pad(c.getUTCMinutes())}`
}
function statusText(status) {
  return ({ pending_ai:'AI 审核中', pending_manual:'待人工审核', approved:'已通过', rejected:'已驳回', invalidated:'场地冲突失效', active:'使用中', awaiting_cleanup:'待离场实拍', completed:'已完成', expired:'已过期', cancelled:'已取消' })[status] || status
}

Page({
  data: {
    bookingId: null,
    booking: null,
    statusText: '',
    timeText: '',
    loading: true,
    qrPath: '',
    qrFetchedAt: '',
    opening: false,
    uploading: false,
    canOpen: false,
    canCleanup: false,
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
      const now = Date.now(), start = new Date(booking.start_time).getTime(), end = new Date(booking.end_time).getTime()
      const canOpen = ['approved', 'active'].includes(booking.status) && now >= start && now < end
      const canCleanup = ['active', 'awaiting_cleanup'].includes(booking.status) && now >= end
      this.setData({
        booking,
        statusText: statusText(booking.status),
        timeText: `${campusTime(booking.start_time)} 至 ${campusTime(booking.end_time)}`,
        canOpen,
        canCleanup,
        loading: false
      })
    } catch (err) {
      this.setData({ loading: false })
      if (showError) wx.showToast({ title: err.message || '读取预约失败', icon: 'none' })
    }
  },

  writeQrFile(base64, contentType) {
    return new Promise((resolve, reject) => {
      const ext = contentType === 'image/jpeg' ? 'jpg' : (contentType === 'image/webp' ? 'webp' : 'png')
      const path = `${wx.env.USER_DATA_PATH}/duxue_qr_${this.data.bookingId}.${ext}`
      wx.getFileSystemManager().writeFile({
        filePath: path, data: base64, encoding: 'base64',
        success: () => resolve(path), fail: reject
      })
    })
  },

  async openDoor() {
    if (this.data.opening) return
    this.setData({ opening: true })
    try {
      const result = await request({ url: `/door/${this.data.bookingId}/checkin`, method: 'POST', loading: true, loadingText: '正在获取门禁码' })
      const qrPath = await this.writeQrFile(result.qr_base64, result.content_type)
      this.setData({ qrPath, qrFetchedAt: campusTime(result.fetched_at), canOpen: true })
      await this.loadBooking(false)
    } catch (err) {
      wx.showToast({ title: err.message || '获取二维码失败', icon: 'none', duration: 3000 })
    } finally { this.setData({ opening: false }) }
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
    } finally { this.setData({ uploading: false }) }
  }
})
