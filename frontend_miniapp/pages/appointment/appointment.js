const { request, getSession } = require('../../utils/request')

function pad(n) { return String(n).padStart(2, '0') }
function campusNowParts() {
  const d = new Date(Date.now() + 8 * 3600000)
  return { y: d.getUTCFullYear(), m: d.getUTCMonth() + 1, day: d.getUTCDate(), h: d.getUTCHours(), min: d.getUTCMinutes() }
}
function ymdFromOffset(days) {
  const now = new Date(Date.now() + 8 * 3600000)
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + days))
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
}
function buildSlots() {
  const result = []
  for (let m = 0; m <= 23 * 60 + 30; m += 30) {
    result.push(`${pad(Math.floor(m / 60))}:${pad(m % 60)}`)
  }
  return result
}

Page({
  data: {
    date: '', minDate: '', maxDate: '',
    slots: [], startIndex: -1, endIndex: -1,
    startText: '请选择', endText: '请选择',
    peopleCount: 1, purpose: '', purposeLength: 0,
    submitting: false,
    durationText: '',
    examples: ['期末考试周复习，需要安静座位', '班级例会，预计 8 人讨论工作', '心理剧排练，希望有较完整活动空间']
  },

  onLoad() {
    const session = getSession()
    if (!session || !session.canBook) {
      wx.showModal({ title: '当前不可预约', content: '账号状态或密码状态不允许发起预约。', showCancel: false, success: () => wx.navigateBack() })
      return
    }
    const slots = buildSlots()
    this.setData({ date: ymdFromOffset(1), minDate: ymdFromOffset(0), maxDate: ymdFromOffset(60), slots })
  },

  onDateChange(e) { this.setData({ date: e.detail.value }); this.ensureFutureSelection() },
  onPeopleInput(e) {
    const value = String(e.detail.value || '').replace(/\D/g, '')
    this.setData({ peopleCount: value ? Math.min(500, Number(value)) : '' })
  },
  onPurposeInput(e) {
    const purpose = e.detail.value
    this.setData({ purpose, purposeLength: purpose.length })
  },
  useExample(e) {
    const purpose = e.currentTarget.dataset.text
    this.setData({ purpose, purposeLength: purpose.length })
  },

  onStartChange(e) {
    const startIndex = Number(e.detail.value)
    let endIndex = this.data.endIndex
    if (endIndex <= startIndex) endIndex = Math.min(startIndex + 1, this.data.slots.length - 1)
    this.setData({
      startIndex,
      endIndex,
      startText: this.data.slots[startIndex],
      endText: endIndex >= 0 ? this.data.slots[endIndex] : '请选择'
    })
    this.updateDuration()
  },

  onEndChange(e) {
    const endIndex = Number(e.detail.value)
    if (this.data.startIndex >= 0 && endIndex <= this.data.startIndex) {
      wx.showToast({ title: '结束时间必须晚于开始时间', icon: 'none' })
      return
    }
    this.setData({ endIndex, endText: this.data.slots[endIndex] })
    this.updateDuration()
  },

  updateDuration() {
    const { startIndex, endIndex } = this.data
    if (startIndex < 0 || endIndex < 0 || endIndex <= startIndex) {
      this.setData({ durationText: '' }); return
    }
    const minutes = (endIndex - startIndex) * 30
    const h = Math.floor(minutes / 60), m = minutes % 60
    this.setData({ durationText: h ? `${h} 小时${m ? ` ${m} 分钟` : ''}` : `${m} 分钟` })
  },

  ensureFutureSelection() {
    // 真正合法性以后端为准；这里只在“今天”选到过去时给即时提示。
    const { date, startIndex, slots } = this.data
    if (startIndex < 0 || date !== ymdFromOffset(0)) return true
    const now = campusNowParts()
    const [h, m] = slots[startIndex].split(':').map(Number)
    if (h * 60 + m <= now.h * 60 + now.min) {
      wx.showToast({ title: '开始时间必须晚于当前时间', icon: 'none' })
      return false
    }
    return true
  },

  async submit() {
    const { date, startIndex, endIndex, slots, peopleCount, purpose, submitting } = this.data
    if (submitting) return
    if (!date || startIndex < 0 || endIndex < 0 || endIndex <= startIndex) {
      wx.showToast({ title: '请选择完整预约时间', icon: 'none' }); return
    }
    if (!this.ensureFutureSelection()) return
    if (!peopleCount || peopleCount < 1) {
      wx.showToast({ title: '请输入预约人数', icon: 'none' }); return
    }
    if (!purpose.trim() || purpose.trim().length < 2) {
      wx.showToast({ title: '请说明具体用途', icon: 'none' }); return
    }

    // 后端当前限定单笔不跨自然日，因此前端只提供 00:00 ~ 23:30 边界内的 30 分钟节点。
    const startTime = `${date}T${slots[startIndex]}:00+08:00`
    const endTime = `${date}T${slots[endIndex]}:00+08:00`
    this.setData({ submitting: true })
    try {
      const result = await request({
        url: '/bookings', method: 'POST', loading: true, loadingText: 'AI 正在审核',
        data: { start_time: startTime, end_time: endTime, people_count: Number(peopleCount), purpose: purpose.trim() }
      })
      const messages = {
        approved: '预约已通过并锁定房间', pending_manual: '已提交，等待管理员审核',
        rejected: '申请未通过', invalidated: '候选房间已被占用'
      }
      wx.showModal({
        title: messages[result.status] || '预约已提交',
        content: result.rejection_reason || result.ai_reason || result.ai_guidance || (result.room_code ? `房间：${result.room_code}` : '可在首页查看最新状态'),
        showCancel: false,
        success: () => wx.navigateBack()
      })
    } catch (err) {
      wx.showToast({ title: err.message || '提交失败', icon: 'none', duration: 3000 })
    } finally {
      this.setData({ submitting: false })
    }
  }
})
