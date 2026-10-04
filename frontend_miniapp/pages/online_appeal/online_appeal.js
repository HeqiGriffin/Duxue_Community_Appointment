const { request, getSession, updateSessionFromProfile } = require('../../utils/request')

function campusTime(iso) {
  if (!iso) return ''
  const d = new Date(iso); if (Number.isNaN(d.getTime())) return String(iso)
  const c = new Date(d.getTime() + 8 * 3600000), pad = n => String(n).padStart(2,'0')
  return `${c.getUTCFullYear()}-${pad(c.getUTCMonth()+1)}-${pad(c.getUTCDate())} ${pad(c.getUTCHours())}:${pad(c.getUTCMinutes())}`
}
const STATUS = { pending: '处理中', approved: '已通过', rejected: '未通过' }

Page({
  data: {
    session: null,
    frozen: false,
    statement: '',
    statementLength: 0,
    bookingId: '',
    bookingTarget: null,
    bookingAppealMode: false,
    canSubmit: false,
    submitting: false,
    appeals: []
  },

  onLoad(options) {
    if (options.bookingId) {
      this.setData({ bookingId: String(options.bookingId), bookingAppealMode: true })
    }
  },
  onShow() { this.refresh() },
  onStatementInput(e) { const statement = e.detail.value; this.setData({ statement, statementLength: statement.length }) },

  async refresh() {
    const session = getSession()
    if (!session) { wx.reLaunch({ url:'/pages/login/login' }); return }
    try {
      const tasks = [request({ url:'/auth/me' }), request({ url:'/appeals/me' })]
      if (this.data.bookingAppealMode && this.data.bookingId) {
        tasks.push(request({ url:`/bookings/${this.data.bookingId}` }))
      }
      const result = await Promise.all(tasks)
      const profile = result[0]
      const appeals = result[1]
      const bookingTarget = result[2] || null
      const next = updateSessionFromProfile(profile)
      const frozen = next.accountStatus === 'frozen'
      const canSubmit = this.data.bookingAppealMode
        ? Boolean(bookingTarget && bookingTarget.status === 'rejected')
        : frozen
      this.setData({
        session: next,
        frozen,
        bookingTarget,
        canSubmit,
        appeals: (appeals || []).map(x => ({
          ...x,
          statusText: STATUS[x.status] || x.status,
          createdText: campusTime(x.created_at),
          typeText: x.appeal_type === 'booking_review' ? '预约人工复核' : '账号解封'
        }))
      })
    } catch (err) { wx.showToast({ title: err.message || '加载失败', icon:'none' }) }
  },

  async submit() {
    const { statement, bookingId, submitting, canSubmit, bookingAppealMode } = this.data
    if (submitting) return
    if (!canSubmit) {
      wx.showToast({ title: bookingAppealMode ? '该预约当前不可再发起人工复核' : '当前账号未被冻结，无需申诉', icon:'none' })
      return
    }
    if (statement.trim().length < 10) { wx.showToast({ title:'情况说明至少 10 个字', icon:'none' }); return }
    this.setData({ submitting:true })
    try {
      await request({
        url:'/appeals', method:'POST', loading:true, loadingText:'正在提交',
        data:{ statement: statement.trim(), booking_id: bookingAppealMode ? Number(bookingId) : null }
      })
      this.setData({ statement:'', statementLength:0 })
      wx.showModal({
        title: bookingAppealMode ? '已转人工复核' : '申诉已提交',
        content: bookingAppealMode ? '该预约已进入管理员人工审核队列，可在首页查看后续结果。' : '管理员审核通过后会恢复账号权限。',
        showCancel: false
      })
      await this.refresh()
    } catch(err) { wx.showToast({ title:err.message || '提交失败', icon:'none', duration:3000 }) }
    finally { this.setData({ submitting:false }) }
  }
})
