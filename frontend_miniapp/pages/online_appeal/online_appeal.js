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
    submitting: false,
    appeals: []
  },

  onLoad(options) {
    if (options.bookingId) this.setData({ bookingId: String(options.bookingId) })
  },
  onShow() { this.refresh() },
  onStatementInput(e) { const statement = e.detail.value; this.setData({ statement, statementLength: statement.length }) },
  onBookingInput(e) { this.setData({ bookingId: String(e.detail.value || '').replace(/\D/g,'') }) },

  async refresh() {
    const session = getSession()
    if (!session) { wx.reLaunch({ url:'/pages/login/login' }); return }
    try {
      const [profile, appeals] = await Promise.all([request({ url:'/auth/me' }), request({ url:'/appeals/me' })])
      const next = updateSessionFromProfile(profile)
      this.setData({
        session: next,
        frozen: next.accountStatus === 'frozen',
        appeals: (appeals || []).map(x => ({ ...x, statusText: STATUS[x.status] || x.status, createdText: campusTime(x.created_at) }))
      })
    } catch (err) { wx.showToast({ title: err.message || '加载失败', icon:'none' }) }
  },

  async submit() {
    const { statement, bookingId, submitting, frozen } = this.data
    if (submitting) return
    if (!frozen) { wx.showToast({ title:'当前账号未被冻结，无需申诉', icon:'none' }); return }
    if (statement.trim().length < 10) { wx.showToast({ title:'情况说明至少 10 个字', icon:'none' }); return }
    this.setData({ submitting:true })
    try {
      await request({
        url:'/appeals', method:'POST', loading:true, loadingText:'正在提交',
        data:{ statement: statement.trim(), booking_id: bookingId ? Number(bookingId) : null }
      })
      this.setData({ statement:'', statementLength:0 })
      wx.showToast({ title:'申诉已提交', icon:'success' })
      await this.refresh()
    } catch(err) { wx.showToast({ title:err.message || '提交失败', icon:'none', duration:3000 }) }
    finally { this.setData({ submitting:false }) }
  }
})
